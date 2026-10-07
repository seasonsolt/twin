"""WeCom smart-bot long connections using the grounded web-chat runtime."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, aclosing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as websocket_connect

from ..config import Settings, WeComBot
from ..persona.chat import HISTORY_TURNS, PersonaChat, no_profile_reply
from ..persona.schema import ChatReply, ChatTurn
from ..persona.store import PersonaStore, stored_identity
from ..service import resolve_citations
from ..util import key_from_env

if TYPE_CHECKING:
    from ..web.backends import Backends
    from ..web.personas import Personas

logger = logging.getLogger(__name__)
FALLBACK = "我现在只看得懂文字和语音，换成文字问我吧。"
APOLOGY = "我这边出了点问题，稍后再问我一次。"
Connect = Callable[[str], AbstractAsyncContextManager[ClientConnection]]
SessionKey = tuple[str, str, str]


class SubscribeFailed(Exception):
    pass


class MissingSecret(Exception):
    pass


class Kicked(Exception):
    pass


@dataclass
class Session:
    history: list[ChatTurn] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    sent: deque[float] = field(default_factory=deque)


def question_text(body: dict[str, Any]) -> str:
    kind = body.get("msgtype")
    if kind in {"text", "voice"}:
        text = body.get(kind, {}).get("content", "")
    elif kind == "mixed":
        text = "\n".join(
            item.get("text", {}).get("content", "")
            for item in body.get("mixed", {}).get("msg_item", [])
            if item.get("msgtype") == "text"
        )
    else:
        return ""
    if body.get("chattype") == "group":
        text = re.sub(r"^@\S+\s*", "", text)
    return str(text).strip()


def citation_footer(store: PersonaStore, settings: Settings, reply: ChatReply) -> str:
    if reply.mode != "grounded" or not reply.citations:
        return ""
    citations = resolve_citations(store, settings, reply.citations, reply.as_of)
    lines = []
    for citation in citations[:2]:
        quote = " ".join(citation.quote.split())
        quote = quote if len(quote) <= 60 else quote[:59] + "…"
        date = f"{citation.date.isoformat()} · " if citation.date else ""
        lines.append(f"> 依据：{date}「{quote}」")
    return "\n\n" + "\n".join(lines) if lines else ""


class WeComBotRunner:
    def __init__(
        self,
        bot: WeComBot,
        settings: Settings,
        backends: Backends,
        *,
        url: str = "wss://openws.work.weixin.qq.com",
        connect: Connect = websocket_connect,
        heartbeat_interval: float = 30,
        backoff_initial: float = 1,
        backoff_max: float = 60,
        subscribe_backoff: float = 300,
        kicked_backoff: float = 60,
        answer_timeout: float = 530,
        rate_window: float = 60,
        sessions: dict[SessionKey, Session] | None = None,
    ) -> None:
        self.bot, self.settings, self.backends = bot, settings, backends
        self.url, self.connect = url, connect
        self.heartbeat_interval = heartbeat_interval
        self.backoff_initial, self.backoff_max = backoff_initial, backoff_max
        self.subscribe_backoff, self.kicked_backoff = subscribe_backoff, kicked_backoff
        self.answer_timeout, self.rate_window = answer_timeout, rate_window
        self.status: Literal["connecting", "connected", "error"] = "connecting"
        self.detail = "连接中…"
        self._send_lock = asyncio.Lock()
        self._seen: OrderedDict[str, None] = OrderedDict()
        self.sessions = sessions if sessions is not None else {}

    async def run(self) -> None:
        backoff = self.backoff_initial
        try:
            while True:
                self.status, self.detail = "connecting", "连接中…"
                delay = backoff
                try:
                    secret = key_from_env(self.bot.secret_env)
                    if not secret:
                        raise MissingSecret
                    async with self.connect(self.url) as socket:
                        try:
                            # Both websocket layers otherwise log private frames at DEBUG level.
                            socket.debug = socket.protocol.debug = False
                            await self._subscribe(socket, secret)
                            backoff = self.backoff_initial
                            self.status, self.detail = "connected", "已连接"
                            logger.info("wecom bot %s connected", self.bot.bot_id)
                            await self._connected(socket)
                        finally:
                            await socket.close()
                except MissingSecret:
                    self.status, self.detail = "error", f"没有读到环境变量 {self.bot.secret_env}"
                    delay = self.subscribe_backoff
                except SubscribeFailed:
                    self.status, self.detail = "error", "凭证无效"
                    delay = self.subscribe_backoff
                except Kicked:
                    self.status, self.detail = "error", "连接被替换，稍后重连"
                    delay = self.kicked_backoff
                except Exception as exc:
                    self.status, self.detail = "error", "连接断开，正在重连"
                    logger.warning("wecom bot %s connection error (%s)", self.bot.bot_id, type(exc).__name__)
                    delay = backoff
                    backoff = min(backoff * 2, self.backoff_max)
                await asyncio.sleep(delay)
        finally:
            self.status, self.detail = "error", "连接已停止"

    async def _send(self, socket: ClientConnection, frame: dict[str, Any]) -> None:
        async with self._send_lock:
            await socket.send(json.dumps(frame, ensure_ascii=False))

    async def _subscribe(self, socket: ClientConnection, secret: str) -> None:
        req_id = uuid.uuid4().hex
        await self._send(
            socket,
            {
                "cmd": "aibot_subscribe",
                "headers": {"req_id": req_id},
                "body": {"bot_id": self.bot.bot_id, "secret": secret},
            },
        )
        async with asyncio.timeout(20):
            while True:
                frame = json.loads(await socket.recv())
                if frame.get("headers", {}).get("req_id") == req_id:
                    if frame.get("errcode", 0) != 0:
                        raise SubscribeFailed
                    return

    async def _heartbeat(self, socket: ClientConnection) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            await self._send(socket, {"cmd": "ping", "headers": {"req_id": uuid.uuid4().hex}})

    async def _connected(self, socket: ClientConnection) -> None:
        tasks: set[asyncio.Task[None]] = set()

        async def read() -> None:
            async for raw in socket:
                frame = json.loads(raw)
                body = frame.get("body", {})
                req_id = frame.get("headers", {}).get("req_id")
                if frame.get("cmd") == "aibot_event_callback":
                    event = body.get("event", {}).get("eventtype")
                    if event == "disconnected_event":
                        raise Kicked
                    if event == "enter_chat" and req_id:
                        task = asyncio.create_task(self._welcome(socket, req_id))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
                elif frame.get("cmd") == "aibot_msg_callback" and req_id:
                    msgid = body.get("msgid")
                    if msgid:
                        if msgid in self._seen:
                            self._seen.move_to_end(msgid)
                            continue
                        self._seen[msgid] = None
                        if len(self._seen) > 2048:
                            self._seen.popitem(last=False)
                    task = asyncio.create_task(self._answer(socket, req_id, body))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)

        reader = asyncio.create_task(read())
        heartbeat = asyncio.create_task(self._heartbeat(socket))
        try:
            done, _ = await asyncio.wait({reader, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            raise ConnectionError
        finally:
            pending = [reader, heartbeat, *tasks]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def _welcome(self, socket: ClientConnection, req_id: str) -> None:
        try:
            async with asyncio.timeout(5):
                name = await asyncio.to_thread(lambda: stored_identity(self.settings.db_path)[0])
                await self._send(
                    socket,
                    {
                        "cmd": "aibot_respond_welcome_msg",
                        "headers": {"req_id": req_id},
                        "body": {
                            "msgtype": "text",
                            "text": {
                                "content": f"你好，我是{name or self.settings.target_name}的数字分身，"
                                "有什么想问我的，直接说就行。"
                            },
                        },
                    },
                )
        except Exception as exc:
            logger.warning("wecom bot %s welcome error (%s)", self.bot.bot_id, type(exc).__name__)

    async def _stream(
        self,
        socket: ClientConnection,
        session: Session,
        req_id: str,
        stream_id: str,
        content: str,
        *,
        finish: bool,
    ) -> bool:
        # Reserve the thirtieth slot for the final, guarded answer; drafts never block generation.
        while True:
            now = time.monotonic()
            while session.sent and now - session.sent[0] >= self.rate_window:
                session.sent.popleft()
            if len(session.sent) < (30 if finish else 29):
                break
            if not finish:
                return False
            await asyncio.sleep(self.rate_window - (now - session.sent[0]))
        session.sent.append(time.monotonic())
        await self._send(
            socket,
            {
                "cmd": "aibot_respond_msg",
                "headers": {"req_id": req_id},
                "body": {"msgtype": "stream", "stream": {"id": stream_id, "finish": finish, "content": content}},
            },
        )
        return True

    async def _answer(self, socket: ClientConnection, req_id: str, body: dict[str, Any]) -> None:
        kind = body.get("chattype", "single")
        peer = body.get("chatid", "") if kind == "group" else body.get("from", {}).get("userid", "")
        session = self.sessions.setdefault((self.bot.persona, kind, peer), Session())
        stream_id = uuid.uuid4().hex
        work = asyncio.create_task(self._produce(socket, session, req_id, stream_id, body))
        try:
            done, _ = await asyncio.wait({work}, timeout=self.answer_timeout)
            if not done:
                work.cancel()
                raise TimeoutError
            work.result()
        except Exception as exc:
            logger.warning("wecom bot %s answer error (%s)", self.bot.bot_id, type(exc).__name__)
            try:
                async with asyncio.timeout(65):
                    await self._stream(socket, session, req_id, stream_id, APOLOGY, finish=True)
            except Exception as send_exc:
                logger.warning("wecom bot %s send error (%s)", self.bot.bot_id, type(send_exc).__name__)
        finally:
            # Send the deadline's final before waiting for retrieval workers to release the store.
            if not work.done() and not work.cancelling():
                work.cancel()
            cleanup = asyncio.gather(work, return_exceptions=True)
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    async def _produce(
        self, socket: ClientConnection, session: Session, req_id: str, stream_id: str, body: dict[str, Any]
    ) -> None:
        async with session.lock:
            question = question_text(body)
            if not question:
                await self._stream(socket, session, req_id, stream_id, FALLBACK, finish=True)
                return
            messages = [*session.history, ChatTurn(role="user", content=question)]
            with PersonaStore(self.settings.db_path) as store:
                if not store.list_items():
                    reply = no_profile_reply(store)
                else:
                    llm, embedder = await asyncio.to_thread(
                        lambda: (self.backends.chat_llm(), self.backends.embedder())
                    )
                    chat = PersonaChat(store, llm, embedder, self.settings)
                    draft, sent, refreshed = "", "", float("-inf")
                    reply = None
                    async with aclosing(chat.stream_reply(messages)) as replies:
                        async for result in replies:
                            if isinstance(result, str):
                                draft += result
                                if (
                                    draft != sent
                                    and time.monotonic() - refreshed >= 1.0
                                    and await self._stream(socket, session, req_id, stream_id, draft, finish=False)
                                ):
                                    sent, refreshed = draft, time.monotonic()
                            else:
                                reply = result
                if reply is None:
                    raise RuntimeError
                final = reply.reply + citation_footer(store, self.settings, reply)
                await self._stream(socket, session, req_id, stream_id, final, finish=True)
            session.history = [*messages, ChatTurn(role="twin", content=reply.reply)][-HISTORY_TURNS * 2 :]


class WeComHub:
    def __init__(self, settings: Settings, registry: Personas, backends: Backends) -> None:
        self.runners: list[WeComBotRunner] = []
        self._missing: list[WeComBot] = []
        self._tasks: list[asyncio.Task[None]] = []
        sessions: dict[SessionKey, Session] = {}
        for bot in settings.wecom.bots:
            try:
                resolved = registry.settings_for(bot.persona)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                self._missing.append(bot)
                continue
            self.runners.append(WeComBotRunner(bot, resolved, backends, url=settings.wecom.url, sessions=sessions))

    async def start(self) -> None:
        if not self._tasks:
            self._tasks = [asyncio.create_task(runner.run()) for runner in self.runners]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def status_for(self, persona_id: str) -> list[dict[str, str]]:
        return [
            {"bot_id": runner.bot.bot_id, "status": runner.status, "detail": runner.detail}
            for runner in self.runners
            if runner.bot.persona == persona_id
        ] + [
            {"bot_id": bot.bot_id, "status": "error", "detail": "分身不存在"}
            for bot in self._missing
            if bot.persona == persona_id
        ]
