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
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as websocket_connect

from ..assets import AssetStore
from ..config import Settings
from ..persona.chat import HISTORY_TURNS, PersonaChat, no_profile_reply
from ..persona.schema import ChatReply, ChatTurn
from ..persona.store import PersonaStore, stored_identity
from ..service import resolve_citations
from ..util import private_directory

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
        bot_id: str,
        secret: str,
        settings: Settings,
        backends: Backends,
        *,
        persona_id: str = "default",
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
        self.bot_id, self.secret, self.persona_id = bot_id, secret, persona_id
        self.settings, self.backends = settings, backends
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
                    async with self.connect(self.url) as socket:
                        try:
                            # Both websocket layers otherwise log private frames at DEBUG level.
                            socket.debug = socket.protocol.debug = False
                            await self._subscribe(socket)
                            backoff = self.backoff_initial
                            self.status, self.detail = "connected", "已连接"
                            logger.info("wecom bot %s connected", self.bot_id)
                            await self._connected(socket)
                        finally:
                            await socket.close()
                except SubscribeFailed:
                    self.status, self.detail = "error", "Bot ID 或 Secret 不对"
                    delay = self.subscribe_backoff
                except Kicked:
                    self.status, self.detail = "error", "连接被替换，稍后重连"
                    logger.info("wecom bot %s disconnected/kicked", self.bot_id)
                    delay = self.kicked_backoff
                except Exception as exc:
                    self.status, self.detail = "error", "连接断开，正在重连"
                    logger.info("wecom bot %s disconnected (%s)", self.bot_id, type(exc).__name__)
                    delay = backoff
                    backoff = min(backoff * 2, self.backoff_max)
                await asyncio.sleep(delay)
        finally:
            self.status, self.detail = "error", "连接已停止"
            logger.info("wecom bot %s disconnected", self.bot_id)

    async def _send(self, socket: ClientConnection, frame: dict[str, Any]) -> None:
        async with self._send_lock:
            await socket.send(json.dumps(frame, ensure_ascii=False))

    async def _subscribe(self, socket: ClientConnection) -> None:
        req_id = uuid.uuid4().hex
        await self._send(
            socket,
            {
                "cmd": "aibot_subscribe",
                "headers": {"req_id": req_id},
                "body": {"bot_id": self.bot_id, "secret": self.secret},
            },
        )
        async with asyncio.timeout(20):
            while True:
                frame = json.loads(await socket.recv())
                if frame.get("headers", {}).get("req_id") == req_id:
                    errcode = frame.get("errcode", 0)
                    if errcode != 0:
                        logger.warning(
                            "wecom bot %s subscribe rejected (errcode=%s)",
                            self.bot_id,
                            errcode if isinstance(errcode, int) else -1,
                        )
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
            logger.warning("wecom bot %s welcome error (%s)", self.bot_id, type(exc).__name__)

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
        session = self.sessions.setdefault((self.persona_id, kind, peer), Session())
        stream_id = uuid.uuid4().hex
        work = asyncio.create_task(self._produce(socket, session, req_id, stream_id, body))
        try:
            done, _ = await asyncio.wait({work}, timeout=self.answer_timeout)
            if not done:
                work.cancel()
                raise TimeoutError
            work.result()
        except Exception as exc:
            logger.warning("wecom bot %s answer error (%s)", self.bot_id, type(exc).__name__)
            try:
                async with asyncio.timeout(65):
                    await self._stream(socket, session, req_id, stream_id, APOLOGY, finish=True)
            except Exception as send_exc:
                logger.warning("wecom bot %s send error (%s)", self.bot_id, type(send_exc).__name__)
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


CONFLICT = "这个机器人已经绑定了另一个分身"


class WeComHub:
    def __init__(self, settings: Settings, registry: Personas, backends: Backends) -> None:
        self.settings, self.registry, self.backends = settings, registry, backends
        self.runners: dict[str, WeComBotRunner] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._errors: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def _path(self, persona_id: str) -> Path:
        return self.registry.settings_for(persona_id).db_path.parent / "channels.json"

    def _read(self, persona_id: str) -> dict[str, Any]:
        path = self._path(persona_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _write(self, persona_id: str, data: dict[str, Any]) -> None:
        path = self._path(persona_id)
        if data:
            private_directory(path.parent)
            AssetStore.write(path, json.dumps(data, ensure_ascii=False).encode())
        else:
            path.unlink(missing_ok=True)

    def _conflicts(self, persona_id: str, bot_id: str) -> bool:
        return any(
            self._read(entry["id"]).get("wecom", {}).get("bot_id") == bot_id
            for entry in self.registry.data["personas"]
            if entry["id"] != persona_id and entry["id"] not in self.registry.removing and not entry.get("deleted_at")
        )

    def _start(self, persona_id: str, binding: dict[str, str]) -> None:
        self._errors.pop(persona_id, None)
        runner = WeComBotRunner(
            binding["bot_id"],
            binding["secret"],
            self.registry.settings_for(persona_id),
            self.backends,
            persona_id=persona_id,
            url=self.settings.wecom.url,
        )
        self.runners[persona_id] = runner
        self._tasks[persona_id] = asyncio.create_task(runner.run())

    async def _stop(self, persona_id: str) -> None:
        task = self._tasks.pop(persona_id, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.runners.pop(persona_id, None)
        self._errors.pop(persona_id, None)

    async def start(self) -> None:
        async with self._lock:
            claimed = {runner.bot_id for runner in self.runners.values()}
            for entry in self.registry.data["personas"]:
                persona_id = entry["id"]
                if entry.get("deleted_at") or persona_id in self.runners:
                    continue
                binding = self._read(persona_id).get("wecom")
                if binding:
                    if binding["bot_id"] in claimed:
                        self._errors[persona_id] = CONFLICT
                    else:
                        self._start(persona_id, binding)
                        claimed.add(binding["bot_id"])

    async def stop(self) -> None:
        async with self._lock:
            for persona_id in list(self._tasks):
                await self._stop(persona_id)

    async def bind(self, persona_id: str, bot_id: str, secret: str | None) -> dict[str, Any]:
        async with self._lock:
            data = self._read(persona_id)
            previous = data.get("wecom", {})
            if secret is None:
                if previous.get("bot_id") != bot_id or not previous.get("secret"):
                    raise HTTPException(400, "请填写 Secret")
                secret = previous["secret"]
            if self._conflicts(persona_id, bot_id):
                raise HTTPException(409, CONFLICT)
            await self._stop(persona_id)
            data["wecom"] = {"bot_id": bot_id, "secret": secret}
            self._write(persona_id, data)
            self._start(persona_id, data["wecom"])
            status = self.status_for(persona_id)
            assert status is not None
            return status

    async def unbind(self, persona_id: str) -> None:
        async with self._lock:
            data = self._read(persona_id)
            if "wecom" not in data:
                raise HTTPException(404, "还没有绑定企业微信")
            await self._stop(persona_id)
            del data["wecom"]
            self._write(persona_id, data)

    async def persona_removed(self, persona_id: str) -> None:
        async with self._lock:
            await self._stop(persona_id)

    async def persona_restored(self, persona_id: str) -> None:
        async with self._lock:
            await self._stop(persona_id)
            try:
                binding = self._read(persona_id).get("wecom")
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                return
            if binding:
                if self._conflicts(persona_id, binding["bot_id"]):
                    self._errors[persona_id] = CONFLICT
                else:
                    self._start(persona_id, binding)

    def status_for(self, persona_id: str) -> dict[str, Any] | None:
        binding = self._read(persona_id).get("wecom")
        if not binding:
            return None
        runner = self.runners.get(persona_id)
        return {
            "bot_id": binding["bot_id"],
            "status": runner.status if runner else "error" if persona_id in self._errors else "connecting",
            "detail": runner.detail if runner else self._errors.get(persona_id, "连接中…"),
            "secret_set": bool(binding.get("secret")),
        }
