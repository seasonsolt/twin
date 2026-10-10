from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve

from twin.channels.wecom import APOLOGY, FALLBACK, WeComBotRunner, WeComHub, citation_footer
from twin.config import AuthSettings, Settings, SMTPSettings, WeComSettings, load_settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.chat import HISTORY_TURNS, PersonaChat, index_persona
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.schema import ChatReply, ChatTurn, EvidenceClass, SourceKind
from twin.persona.sources import parse_chat
from twin.persona.store import PersonaStore
from twin.web.app import create_app
from twin.web.backends import Backends
from twin.web.jobs import JobManager, describe_error
from twin.web.personas import Personas

BOT_ID = "aibTest"
SECRET = "test-secret-not-for-logs"


def reply(text: str = "最终回答", *, mode: str = "general", citations: list[str] | None = None) -> ChatReply:
    return ChatReply.model_validate(
        {
            "reply": text,
            "mode": mode,
            "citations": citations or [],
            "confidence": 0.8,
            "abstain": mode == "abstain",
            "abstain_reason": "",
            "retrieved_ids": [],
        }
    )


def message(msgid: str = "m1", **body: Any) -> dict[str, Any]:
    return {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": f"req-{msgid}"},
        "body": {
            "msgid": msgid,
            "aibotid": BOT_ID,
            "chattype": "single",
            "from": {"userid": "private-user"},
            "msgtype": "text",
            "text": {"content": "私密问题"},
            **body,
        },
    }


class Peer:
    def __init__(self) -> None:
        self.socket: ServerConnection
        self.frames: asyncio.Queue[tuple[float, dict[str, Any]]] = asyncio.Queue()
        self.subscribe: dict[str, Any] = {}

    async def send(self, frame: dict[str, Any]) -> None:
        await self.socket.send(json.dumps(frame))

    async def receive(self, cmd: str, req_id: str | None = None) -> list[tuple[float, dict[str, Any]]]:
        result = []
        async with asyncio.timeout(4):
            while True:
                stamp, frame = await self.frames.get()
                if frame["cmd"] != cmd or (req_id and frame["headers"]["req_id"] != req_id):
                    continue
                result.append((stamp, frame))
                if cmd != "aibot_respond_msg" or frame["body"]["stream"]["finish"]:
                    return result


@asynccontextmanager
async def running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ack: dict[str, Any] | None = None,
    profile: bool = True,
    **options: Any,
) -> AsyncIterator[tuple[WeComBotRunner, Peer]]:
    settings = Settings(db_path=tmp_path / "twin.db", target_name="配置姓名")
    with PersonaStore(settings.db_path) as store:
        store.set_meta("identity:name", "张三")
        if profile:
            store.replace_facet_items(
                "2.1", [PersonaItem(item_id="pi_test", facet_id="2.1", statement="先核实", evidence=[])]
            )
    peer = Peer()
    ready = asyncio.Event()

    async def handler(socket: ServerConnection) -> None:
        peer.socket = socket
        peer.subscribe = json.loads(await socket.recv())
        await socket.send(json.dumps({"headers": peer.subscribe["headers"], **(ack or {})}))
        ready.set()
        async for raw in socket:
            await peer.frames.put((time.monotonic(), json.loads(raw)))

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        calls = []

        def connector(address: str) -> Any:
            assert address == url
            calls.append(address)
            return connect(address)

        runner = WeComBotRunner(
            BOT_ID,
            SECRET,
            settings,
            Backends(settings, lambda: FakeLLM(lambda *_: {}), HashingEmbedder),
            url=url,
            connect=connector,
            **options,
        )
        task = asyncio.create_task(runner.run())
        try:
            await asyncio.wait_for(ready.wait(), 3)
            yield runner, peer
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled()
        assert calls


def test_subscribe_heartbeat_and_welcome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def check() -> None:
        async with running(tmp_path, monkeypatch, heartbeat_interval=0.02) as (runner, peer):
            assert peer.subscribe["cmd"] == "aibot_subscribe"
            assert peer.subscribe["body"] == {"bot_id": BOT_ID, "secret": SECRET}
            assert peer.subscribe["headers"]["req_id"]
            ping = (await peer.receive("ping"))[0][1]
            assert ping["headers"]["req_id"] != peer.subscribe["headers"]["req_id"]
            assert "body" not in ping and runner.status == "connected"
            await peer.send(
                {
                    "cmd": "aibot_event_callback",
                    "headers": {"req_id": "welcome"},
                    "body": {"event": {"eventtype": "enter_chat"}},
                }
            )
            welcome = (await peer.receive("aibot_respond_welcome_msg"))[0][1]
            assert welcome["headers"]["req_id"] == "welcome"
            assert welcome["body"] == {
                "msgtype": "text",
                "text": {"content": "你好，我是张三的数字分身，有什么想问我的，直接说就行。"},
            }

    asyncio.run(check())


def test_cumulative_throttled_stream_and_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    async def stream(self: PersonaChat, messages: Sequence[ChatTurn]) -> AsyncIterator[str | ChatReply]:
        seen.append(list(messages))
        yield "草"
        yield "稿"
        await asyncio.sleep(1.05)
        yield "第三段"
        yield ""
        yield reply("核验后的最终回答")

    monkeypatch.setattr(PersonaChat, "stream_reply", stream)

    async def check() -> None:
        async with running(tmp_path, monkeypatch) as (runner, peer):
            await peer.send(message())
            frames = await peer.receive("aibot_respond_msg", "req-m1")
            streams = [frame["body"]["stream"] for _, frame in frames]
            assert [s["content"] for s in streams] == ["草", "草稿第三段", "核验后的最终回答"]
            assert [s["finish"] for s in streams] == [False, False, True]
            assert len({s["id"] for s in streams}) == 1
            assert frames[1][0] - frames[0][0] >= 1
            await peer.send(message("m2"))
            await peer.receive("aibot_respond_msg", "req-m2")
            assert [m.role for m in seen[-1]] == ["user", "twin", "user"]
            assert seen[-1][1].content == "核验后的最终回答"
            assert len(next(iter(runner.sessions.values())).history) == 4

    asyncio.run(check())


@pytest.mark.parametrize(
    ("body", "question"),
    [
        ({"chattype": "group", "chatid": "group-1", "text": {"content": "@BotName 怎么做？"}}, "怎么做？"),
        ({"msgtype": "voice", "voice": {"content": "转写的语音"}}, "转写的语音"),
        (
            {
                "msgtype": "mixed",
                "mixed": {
                    "msg_item": [
                        {"msgtype": "text", "text": {"content": "第一段"}},
                        {"msgtype": "image"},
                        {"msgtype": "text", "text": {"content": "第二段"}},
                    ]
                },
            },
            "第一段\n第二段",
        ),
        ({"text": {"content": "@BotName 保留单聊提及"}}, "@BotName 保留单聊提及"),
        ({"msgtype": "image"}, None),
        ({"msgtype": "file"}, None),
        ({"text": {"content": "  "}}, None),
    ],
)
def test_extract_and_dedupe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: dict[str, Any], question: str | None
) -> None:
    seen = []

    async def stream(self: PersonaChat, messages: Sequence[ChatTurn]) -> AsyncIterator[str | ChatReply]:
        seen.append(messages[-1].content)
        yield reply()

    monkeypatch.setattr(PersonaChat, "stream_reply", stream)

    async def check() -> None:
        async with running(tmp_path, monkeypatch) as (runner, peer):
            await peer.send(message(**body))
            await peer.send(message(**body))
            frames = await peer.receive("aibot_respond_msg")
            assert frames[-1][1]["body"]["stream"]["content"] == ("最终回答" if question else FALLBACK)
            await asyncio.sleep(0.03)
            assert peer.frames.empty()
            assert len(runner._seen) == 1
            assert seen == ([question] if question else [])

    asyncio.run(check())


def test_error_private_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="websockets.client")

    async def stream(self: PersonaChat, messages: Sequence[ChatTurn]) -> AsyncIterator[str | ChatReply]:
        yield "私密草稿"
        raise ValueError("secret exception body")

    monkeypatch.setattr(PersonaChat, "stream_reply", stream)

    async def check() -> None:
        async with running(tmp_path, monkeypatch) as (_, peer):
            await peer.send(message())
            frames = await peer.receive("aibot_respond_msg")
            assert frames[-1][1]["body"]["stream"]["content"] == APOLOGY
            assert frames[-1][1]["body"]["stream"]["finish"]
            assert "secret exception body" not in json.dumps(frames)

    asyncio.run(check())
    assert "ValueError" in caplog.text
    for private in ["secret exception body", "私密问题", "私密草稿", "private-user", "test-secret-not-for-logs"]:
        assert private not in caplog.text


def seed_citations(settings: Settings) -> list[str]:
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_chat("群.txt", "2025-03-02 10:00 张三：先核实证据\n", settings))
        expression = store.list_expressions(target_only=True)[0]
        store.replace_facet_items(
            "2.1",
            [
                PersonaItem(
                    item_id="pi_test",
                    facet_id="2.1",
                    statement="核实",
                    evidence=[
                        PEvidence(
                            expression_id=expression.expression_id,
                            source_id=expression.source_id,
                            source_kind=SourceKind.CHAT,
                            evidence_class=EvidenceClass.BEHAVIOR,
                            date=dt.date(2025, 3, 2),
                            quote="先核实证据",
                        )
                    ],
                )
            ],
        )
    return ["pi_test", expression.expression_id]


@pytest.mark.parametrize("mode", ["grounded", "general", "inferred", "abstain"])
def test_citation_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    refs: list[str] = []

    async def stream(self: PersonaChat, messages: Sequence[ChatTurn]) -> AsyncIterator[str | ChatReply]:
        yield reply(mode=mode, citations=refs)

    monkeypatch.setattr(PersonaChat, "stream_reply", stream)

    async def check() -> None:
        nonlocal refs
        async with running(tmp_path, monkeypatch) as (runner, peer):
            runner.settings.target_name = "张三"
            refs = seed_citations(runner.settings)
            await peer.send(message())
            frame = (await peer.receive("aibot_respond_msg"))[-1][1]
            content = frame["body"]["stream"]["content"]
            assert content == (
                "最终回答\n\n> 依据：2025-03-02 · 「先核实证据」\n> 依据：2025-03-02 · 「先核实证据」"
                if mode == "grounded"
                else "最终回答\n\n> 以上是按资料推测，不是本人说过的话"
                if mode == "inferred"
                else "最终回答"
            )

    asyncio.run(check())


def test_footer_clip_and_undated(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", target_name="张三")
    refs = seed_citations(settings)
    with PersonaStore(settings.db_path) as store:
        item = store.list_items()[0]
        item.evidence[0].quote = "长" * 80
        item.evidence[0].date = None
        store.replace_facet_items(item.facet_id, [item])
        footer = citation_footer(store, settings, reply(mode="grounded", citations=[refs[0]] * 3))
        assert footer.count("> 依据：") == 2
        assert "·" not in footer and "「" + "长" * 59 + "…」" in footer


def test_no_profile_avoids_backends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any) -> Any:
        pytest.fail("must not construct a backend without memories")

    monkeypatch.setattr(Backends, "chat_llm", forbidden)

    async def check() -> None:
        async with running(tmp_path, monkeypatch, profile=False) as (_, peer):
            await peer.send(message())
            frames = await peer.receive("aibot_respond_msg")
            assert len(frames) == 1 and frames[0][1]["body"]["stream"]["finish"]
            assert frames[0][1]["body"]["stream"]["content"] != APOLOGY

    asyncio.run(check())


def test_subscribe_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    async def check() -> None:
        async with running(tmp_path, monkeypatch, ack={"errcode": 400, "errmsg": "sensitive"}) as (runner, _):
            await asyncio.sleep(0.03)
            assert runner.status == "error" and runner.detail == "Bot ID 或 Secret 不对"

    asyncio.run(check())
    assert "wecom bot aibTest subscribe rejected (errcode=400)" in caplog.text
    assert "sensitive" not in caplog.text
    assert SECRET not in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.parametrize("kicked", [False, True])
def test_reconnect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kicked: bool) -> None:
    async def check() -> None:
        async with running(tmp_path, monkeypatch, backoff_initial=0.03, kicked_backoff=0.06) as (runner, peer):
            first = peer.subscribe["headers"]["req_id"]
            stamp = time.monotonic()
            if kicked:
                await peer.send({"cmd": "aibot_event_callback", "body": {"event": {"eventtype": "disconnected_event"}}})
            else:
                await peer.socket.close()
            async with asyncio.timeout(3):
                while peer.subscribe["headers"]["req_id"] == first:
                    await asyncio.sleep(0.005)
            assert time.monotonic() - stamp >= (0.06 if kicked else 0.03)
            await asyncio.sleep(0.01)
            assert runner.status == "connected"

    asyncio.run(check())


def test_history_bound_and_session_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    async def stream(self: PersonaChat, messages: Sequence[ChatTurn]) -> AsyncIterator[str | ChatReply]:
        seen.append(list(messages))
        yield reply()

    monkeypatch.setattr(PersonaChat, "stream_reply", stream)

    async def check() -> None:
        async with running(tmp_path, monkeypatch) as (runner, peer):
            for index in range(HISTORY_TURNS + 2):
                await peer.send(message(str(index)))
                await peer.receive("aibot_respond_msg")
            assert len(next(iter(runner.sessions.values())).history) == HISTORY_TURNS * 2
            await peer.send(message("group", chattype="group", chatid="group"))
            await peer.receive("aibot_respond_msg")
            assert len(seen[-1]) == 1
            await peer.send(message("other", **{"from": {"userid": "other"}}))
            await peer.receive("aibot_respond_msg")
            assert len(seen[-1]) == 1

    asyncio.run(check())


def test_rate_limit_reserves_final(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def stream(self: PersonaChat, messages: Sequence[ChatTurn]) -> AsyncIterator[str | ChatReply]:
        yield "草稿"
        yield reply()

    monkeypatch.setattr(PersonaChat, "stream_reply", stream)

    async def check() -> None:
        async with running(tmp_path, monkeypatch, rate_window=0.15) as (runner, peer):
            from twin.channels.wecom import Session

            session = Session()
            session.sent.extend([time.monotonic()] * 29)
            runner.sessions[("default", "single", "private-user")] = session
            await peer.send(message())
            frames = await peer.receive("aibot_respond_msg")
            assert len(frames) == 1 and frames[0][1]["body"]["stream"]["finish"]
            stamp = time.monotonic()
            await peer.send(message("next"))
            frames = await peer.receive("aibot_respond_msg")
            assert frames[-1][0] - stamp >= 0.10
            assert len(session.sent) <= 30

    asyncio.run(check())


def test_answer_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    closed = []

    async def stream(self: PersonaChat, messages: Sequence[ChatTurn]) -> AsyncIterator[str | ChatReply]:
        try:
            yield "草稿"
            await asyncio.sleep(10)
        finally:
            closed.append(True)

    monkeypatch.setattr(PersonaChat, "stream_reply", stream)

    async def check() -> None:
        async with running(tmp_path, monkeypatch, answer_timeout=0.03) as (_, peer):
            await peer.send(message())
            frames = await peer.receive("aibot_respond_msg")
            assert frames[-1][1]["body"]["stream"]["content"] == APOLOGY
            assert closed == [True]

    asyncio.run(check())


@contextmanager
def local_channels(tmp_path: Path) -> Iterator[tuple[TestClient, WeComHub, asyncio.Queue[Peer]]]:
    settings = Settings(db_path=tmp_path / "twin.db")
    app = create_app(settings)
    peers: asyncio.Queue[Peer] = asyncio.Queue()

    async def handler(socket: ServerConnection) -> None:
        peer = Peer()
        peer.socket = socket
        peer.subscribe = json.loads(await socket.recv())
        await socket.send(json.dumps({"headers": peer.subscribe["headers"], "errcode": 0}))
        await peers.put(peer)
        async for raw in socket:
            await peer.frames.put((time.monotonic(), json.loads(raw)))

    async def start_server() -> Any:
        server = await serve(handler, "127.0.0.1", 0)
        settings.wecom.url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        return server

    with TestClient(app, base_url="http://localhost", headers={"X-Twin": "1"}) as client:
        assert client.portal is not None
        server = client.portal.call(start_server)
        try:
            yield client, app.state.channels, peers
        finally:
            client.portal.call(app.state.channels.stop)
            client.portal.call(server.close)
            client.portal.call(server.wait_closed)


def next_peer(client: TestClient, peers: asyncio.Queue[Peer]) -> Peer:
    async def receive() -> Peer:
        return await asyncio.wait_for(peers.get(), 3)

    assert client.portal is not None
    return client.portal.call(receive)


def assert_closed(client: TestClient, peer: Peer) -> None:
    assert client.portal is not None
    client.portal.call(peer.socket.wait_closed)
    assert peer.socket.close_code == 1000


def test_channels_binding_storage_and_runner(tmp_path: Path) -> None:
    with local_channels(tmp_path) as (client, hub, peers):
        assert client.get("/api/channels").json() == {"wecom": None}
        assert client.get("/api/channels", headers={"X-Twin-Persona": "missing"}).status_code == 404
        assert client.delete("/api/channels/wecom").json() == {"detail": "还没有绑定企业微信"}
        assert client.delete("/api/channels/wecom").status_code == 404
        missing = client.put("/api/channels/wecom", json={"bot_id": BOT_ID})
        assert missing.status_code == 400 and missing.json()["detail"] == "请填写 Secret"
        result = client.put("/api/channels/wecom", json={"bot_id": f" {BOT_ID} ", "secret": f" {SECRET} "})
        assert result.status_code == 200
        assert result.json() == {"bot_id": BOT_ID, "status": "connecting", "detail": "连接中…", "secret_set": True}
        first = next_peer(client, peers)
        assert first.subscribe["body"] == {"bot_id": BOT_ID, "secret": SECRET}
        path = tmp_path / "channels.json"
        assert path.stat().st_mode & 0o777 == 0o600
        assert json.loads(path.read_text()) == {"wecom": {"bot_id": BOT_ID, "secret": SECRET}}
        status = client.get("/api/channels")
        assert status.json()["wecom"]["status"] == "connected"
        assert SECRET not in status.text and '"secret"' not in status.text
        old_runner = hub.runners["default"]
        assert client.put("/api/channels/wecom", json={"bot_id": BOT_ID, "secret": None}).status_code == 200
        second = next_peer(client, peers)
        assert_closed(client, first)
        assert hub.runners["default"] is not old_runner
        assert second.subscribe["body"]["secret"] == SECRET
        changed = client.put("/api/channels/wecom", json={"bot_id": "newBot", "secret": None})
        assert changed.status_code == 400 and changed.json()["detail"] == "请填写 Secret"
        assert hub.runners["default"].bot_id == BOT_ID
        assert client.put("/api/channels/wecom", json={"bot_id": "newBot", "secret": "rotated"}).status_code == 200
        third = next_peer(client, peers)
        assert_closed(client, second)
        assert third.subscribe["body"] == {"bot_id": "newBot", "secret": "rotated"}
        assert client.delete("/api/channels/wecom").json() == {"deleted": True}
        assert_closed(client, third)
        assert not path.exists() and not hub.runners and not hub._tasks
        assert client.get("/api/channels").json() == {"wecom": None}


def test_unbind_preserves_sibling_channels(tmp_path: Path) -> None:
    with local_channels(tmp_path) as (client, _, peers):
        client.put("/api/channels/wecom", json={"bot_id": BOT_ID, "secret": SECRET})
        next_peer(client, peers)
        path = tmp_path / "channels.json"
        data = json.loads(path.read_text())
        data["feishu"] = {"app_id": "future"}
        path.write_text(json.dumps(data))
        assert client.delete("/api/channels/wecom").status_code == 200
        assert json.loads(path.read_text()) == {"feishu": {"app_id": "future"}}
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"bot_id": ""},
        {"bot_id": " "},
        {"bot_id": "bad/id"},
        {"bot_id": "机器"},
        {"bot_id": "a" * 129},
        {"bot_id": BOT_ID, "secret": " "},
        {"bot_id": BOT_ID, "secret": "s" * 257},
        {"bot_id": BOT_ID, "secret": 123},
    ],
)
def test_binding_validation(tmp_path: Path, body: dict[str, Any]) -> None:
    with TestClient(create_app(Settings(db_path=tmp_path / "twin.db")), base_url="http://localhost") as client:
        result = client.put("/api/channels/wecom", json=body, headers={"X-Twin": "1"})
        assert result.status_code == 400
        assert "请求参数有误" in result.json()["detail"]
        assert not (tmp_path / "channels.json").exists()


def test_conflict_delete_and_restore(tmp_path: Path) -> None:
    with local_channels(tmp_path) as (client, hub, peers):
        persona_id = client.post("/api/personas", json={"name": "分身"}).json()["id"]
        headers = {"X-Twin-Persona": persona_id}
        binding = {"bot_id": BOT_ID, "secret": SECRET}
        assert client.put("/api/channels/wecom", json=binding, headers=headers).status_code == 200
        first = next_peer(client, peers)
        conflict = client.put("/api/channels/wecom", json=binding)
        assert conflict.status_code == 409 and conflict.json()["detail"] == "这个机器人已经绑定了另一个分身"
        directory = tmp_path / "personas" / persona_id
        assert client.delete(f"/api/personas/{persona_id}").status_code == 200
        assert_closed(client, first)
        assert persona_id not in hub.runners and not directory.exists()
        trash = client.get("/api/personas/trash").json()
        assert len(trash) == 1
        assert list((tmp_path / "trash").glob("*/channels.json"))
        assert client.post(f"/api/personas/{persona_id}/restore").status_code == 200
        second = next_peer(client, peers)
        assert second.subscribe["body"] == binding
        assert (directory / "channels.json").stat().st_mode & 0o777 == 0o600
        assert client.delete(f"/api/personas/{persona_id}").status_code == 200
        assert_closed(client, second)
        assert client.put("/api/channels/wecom", json=binding).status_code == 200
        default = next_peer(client, peers)
        assert client.post(f"/api/personas/{persona_id}/restore").status_code == 200
        status = client.get("/api/channels", headers=headers).json()["wecom"]
        assert status["status"] == "error" and status["detail"] == "这个机器人已经绑定了另一个分身"
        assert persona_id not in hub.runners and peers.empty()
        assert default.socket.close_code is None
        assert client.delete("/api/channels/wecom", headers=headers).status_code == 200


def test_hub_loads_bindings_on_start(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    registry = Personas(settings, JobManager(1, describe_error))
    other = "p-test"
    deleted = "p-deleted"
    registry.data["personas"].extend([{"id": other}, {"id": deleted, "deleted_at": "2025-01-01"}])
    for persona_id in ("default", other, deleted):
        directory = tmp_path if persona_id == "default" else tmp_path / "personas" / persona_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "channels.json").write_text(json.dumps({"wecom": {"bot_id": persona_id, "secret": SECRET}}))
    hub = WeComHub(settings, registry, Backends(settings, None, None))
    subscribed: asyncio.Queue[dict[str, str]] = asyncio.Queue()

    async def handler(socket: ServerConnection) -> None:
        frame = json.loads(await socket.recv())
        await socket.send(json.dumps({"headers": frame["headers"]}))
        await subscribed.put(frame["body"])
        await socket.wait_closed()

    async def check() -> None:
        async with serve(handler, "127.0.0.1", 0) as server:
            settings.wecom.url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            try:
                await hub.start()
                await hub.start()
                bodies = [await asyncio.wait_for(subscribed.get(), 3) for _ in range(2)]
                assert {body["bot_id"] for body in bodies} == {"default", other}
                assert all(body["secret"] == SECRET for body in bodies)
                assert len(hub._tasks) == 2 and deleted not in hub.runners
            finally:
                await hub.stop()
                await hub.stop()
            assert not hub._tasks

    asyncio.run(check())


def test_real_runtime_guards_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def check() -> None:
        async with running(tmp_path, monkeypatch) as (runner, peer):
            runner.settings.target_name = "张三"
            refs = seed_citations(runner.settings)
            llm = FakeLLM(
                lambda *_: {"reply": "先『核实证据』，不要『凭空编造』。", "citations": refs, "confidence": 0.8}
            )
            runner.backends = Backends(runner.settings, lambda: llm, HashingEmbedder)
            with PersonaStore(runner.settings.db_path) as store:
                index_persona(store, HashingEmbedder(), runner.settings)
            await peer.send(message())
            frames = await peer.receive("aibot_respond_msg")
            assert "『凭空编造』" in frames[0][1]["body"]["stream"]["content"]
            final = frames[-1][1]["body"]["stream"]["content"]
            assert final.startswith("先『核实证据』，不要凭空编造。\n\n> 依据：")
            with PersonaStore(runner.settings.db_path) as store:
                assert store._db.execute("SELECT COUNT(*) FROM p_chat_log").fetchone()[0] == 1

    asyncio.run(check())


def test_chat_tasks_do_not_block_heartbeat_or_other_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = asyncio.Event()
    closed = []

    async def stream(self: PersonaChat, messages: Sequence[ChatTurn]) -> AsyncIterator[str | ChatReply]:
        if messages[-1].content == "等待":
            try:
                blocked.set()
                yield "草稿"
                await asyncio.sleep(10)
            finally:
                closed.append(True)
        else:
            yield reply()

    monkeypatch.setattr(PersonaChat, "stream_reply", stream)

    async def check() -> None:
        async with running(tmp_path, monkeypatch, heartbeat_interval=0.01) as (_, peer):
            await peer.send(message(text={"content": "等待"}))
            await asyncio.wait_for(blocked.wait(), 2)
            await peer.send(message("fast", **{"from": {"userid": "other"}}))
            assert (await peer.receive("aibot_respond_msg", "req-fast"))[-1][1]["body"]["stream"]["finish"]
            await peer.receive("ping")
        assert closed == [True]
        assert peer.socket.close_code == 1000

    asyncio.run(check())


def test_subscribe_retry_uses_bound_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def check() -> None:
        async with running(tmp_path, monkeypatch, ack={"errcode": 1}, subscribe_backoff=0.08) as (runner, peer):
            first = peer.subscribe["headers"]["req_id"]
            stamp = time.monotonic()
            await asyncio.sleep(0.01)
            assert runner.status == "error"
            async with asyncio.timeout(2):
                while peer.subscribe["headers"]["req_id"] == first:
                    await asyncio.sleep(0.005)
            assert time.monotonic() - stamp >= 0.08
            assert peer.subscribe["body"]["secret"] == SECRET

    asyncio.run(check())


def test_channels_auth_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_SMTP_PASSWORD", "test-only")
    codes = []
    monkeypatch.setattr("twin.web.auth.send_code", lambda smtp, email, code: codes.append(code))
    settings = Settings(
        db_path=tmp_path / "twin.db",
        auth=AuthSettings(
            enabled=True,
            allowed_domains=[],
            allowed_emails=["admin@example.com", "member@example.com"],
            admin_emails=["admin@example.com"],
            smtp=SMTPSettings(host="smtp.example.com", username="test", from_address="twin@example.com"),
        ),
    )
    app = create_app(settings)
    app.state.personas.data["personas"][0]["public"] = True
    app.state.personas.save()
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/channels").status_code == 401
        for email, expected in [("member@example.com", 403), ("admin@example.com", 200)]:
            client.post("/api/auth/request", json={"email": email}, headers={"X-Twin": "1"})
            result = client.post("/api/auth/verify", json={"email": email, "code": codes[-1]}, headers={"X-Twin": "1"})
            assert result.status_code == 200
            assert client.get("/api/channels", headers={"X-Twin-Persona": "default"}).status_code == expected
            if email == "member@example.com":
                headers = {"X-Twin": "1", "X-Twin-Persona": "default"}
                assert (
                    client.put(
                        "/api/channels/wecom", json={"bot_id": BOT_ID, "secret": SECRET}, headers=headers
                    ).status_code
                    == 403
                )
                assert client.delete("/api/channels/wecom", headers=headers).status_code == 403


def test_deadline_final_precedes_slow_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    closed = []

    async def stream(self: PersonaChat, messages: Sequence[ChatTurn]) -> AsyncIterator[str | ChatReply]:
        try:
            yield "草稿"
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.2)
            closed.append(True)
            raise

    monkeypatch.setattr(PersonaChat, "stream_reply", stream)

    async def check() -> None:
        async with running(tmp_path, monkeypatch, answer_timeout=0.03) as (_, peer):
            stamp = time.monotonic()
            await peer.send(message())
            frames = await peer.receive("aibot_respond_msg")
            assert frames[-1][1]["body"]["stream"]["content"] == APOLOGY
            assert frames[-1][0] - stamp < 0.2 and not closed
        assert closed == [True]

    asyncio.run(check())


def test_dedupe_lru_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    async def answer(self: WeComBotRunner, socket: Any, req_id: str, body: dict[str, Any]) -> None:
        seen.append(body["msgid"])

    monkeypatch.setattr(WeComBotRunner, "_answer", answer)

    async def check() -> None:
        async with running(tmp_path, monkeypatch) as (runner, peer):
            for index in range(2050):
                await peer.send(message(str(index)))
            async with asyncio.timeout(4):
                while len(seen) < 2050:
                    await asyncio.sleep(0.005)
            assert len(runner._seen) == 2048 and "0" not in runner._seen
            await peer.send(message("2049"))
            await peer.send(message("0"))
            async with asyncio.timeout(2):
                while len(seen) < 2051:
                    await asyncio.sleep(0.005)
            assert seen[-1] == "0" and seen.count("2049") == 1
            assert len(runner._seen) == 2048

    asyncio.run(check())


def test_lifecycle_hooks_run_without_the_registry_lock(tmp_path: Path) -> None:
    app = create_app(Settings(db_path=tmp_path / "twin.db"))
    registry = app.state.personas
    removed, restored = registry.on_removed, registry.on_restored
    calls = []

    def on_removed(persona_id: str) -> None:
        assert not registry.lock._is_owned()
        removed(persona_id)
        calls.append(("removed", persona_id))

    def on_restored(persona_id: str) -> None:
        assert not registry.lock._is_owned()
        restored(persona_id)
        calls.append(("restored", persona_id))

    registry.on_removed, registry.on_restored = on_removed, on_restored
    with TestClient(app, base_url="http://localhost", headers={"X-Twin": "1"}) as client:
        persona_id = client.post("/api/personas", json={"name": "分身"}).json()["id"]
        assert client.delete(f"/api/personas/{persona_id}").status_code == 200
        assert client.post(f"/api/personas/{persona_id}/restore").status_code == 200
    assert calls == [("removed", persona_id), ("restored", persona_id)]


def test_ui_channel_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from twin import cli

    channels_logger = logging.getLogger("twin.channels")
    root_handlers = list(logging.getLogger().handlers)
    monkeypatch.setattr(channels_logger, "handlers", [])
    monkeypatch.setattr(channels_logger, "level", logging.NOTSET)
    monkeypatch.setattr(channels_logger, "propagate", True)
    monkeypatch.setattr(cli, "_settings", lambda _: Settings(db_path=tmp_path / "twin.db"))

    def serve(*args: Any, **kwargs: Any) -> None:
        assert len(channels_logger.handlers) == 1
        handler = channels_logger.handlers[0]
        assert handler.level == logging.INFO
        assert channels_logger.level == logging.INFO and not channels_logger.propagate
        logging.getLogger("twin.channels.wecom").info("wecom bot aibTest connected")
        assert logging.getLogger().handlers == root_handlers

    monkeypatch.setattr(cli, "_serve", serve)
    result = CliRunner().invoke(cli.app, ["ui"])
    assert result.exit_code == 0, result.exception
    assert result.stderr.count("INFO twin.channels.wecom: wecom bot aibTest connected") == 1


def test_legacy_config_ignored(tmp_path: Path) -> None:
    config = tmp_path / "twin.toml"
    config.write_text(
        '[[wecom.bots]]\npersona = "default"\nbot_id = "aibOld"\nsecret_env = "OLD_SECRET"\n'
        '[[wecom.bots]]\nbot_id = "aibOld"\n'
    )
    assert load_settings(config).wecom.model_dump() == {"url": "wss://openws.work.weixin.qq.com"}
    assert WeComSettings().url == "wss://openws.work.weixin.qq.com"
