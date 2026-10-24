"""员工 1b: a colleague signed in through the company login finds their voice in meetings others uploaded, hears
one sentence of each voice and nothing more, and makes their own twin from the ones they confirm."""

from __future__ import annotations

import io
import math
import shutil
import subprocess
import threading
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_team import recording, until
from test_web_auth import FakeLogin

from twin.config import ASRSettings, AuthSettings, LibrarySettings, Settings, SSOSettings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media.ingest import CommandTranscriber, Segment, Speaker
from twin.media.library import Library, owner_key
from twin.media.team import Team
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")

CSRF = {"X-Twin": "1"}
UPLOADER, MEMBER, OTHER, NO_ADDRESS, ADMIN = "cookie-w", "cookie-z", "cookie-o", "cookie-n", "cookie-a"
ZHANG = [0.98, 0.2, 0.0]


class FakeVoice(CommandTranscriber):
    """Gives every recorded sentence the voiceprint ``FakeVoice.print`` (asr-funasr 1.3.0's ``embed``)."""

    print: list[float] | None = ZHANG

    def __init__(self) -> None:
        super().__init__("unused")

    def embed(self, voice: Path) -> list[float] | None:
        assert voice.is_file() and voice.suffix == ".wav"
        return FakeVoice.print


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from sso_app(tmp_path, monkeypatch)


def sso_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The app behind the company login, with 王五, 张三 and 赵六 by their accounts, someone the login gives no
    account and an administrator; switch between them with ``as_``."""

    def soon(delay: float, fn: Any) -> threading.Timer:
        timer = threading.Timer(0.01, fn)
        timer.daemon = True
        timer.start()
        return timer

    monkeypatch.setattr(PersonaProcessing, "_timer", staticmethod(soon))
    monkeypatch.setattr("twin.web.voice.make_transcriber", lambda _: FakeVoice())
    monkeypatch.delenv("TWIN_SMTP_PASSWORD", raising=False)
    FakeVoice.print = ZHANG
    login = FakeLogin()
    login.sessions = {
        UPLOADER: {"subject": "2001", "display_name": "王五", "account": "wangwu"},
        MEMBER: {"subject": "2002", "display_name": "张三", "account": "zhangsan"},
        OTHER: {"subject": "2003", "display_name": "赵六", "account": "zhaoliu"},
        NO_ADDRESS: {"subject": "2004", "display_name": "外包"},
        ADMIN: {"subject": "9999", "display_name": "管理员", "account": "admin"},
    }
    settings = Settings(
        db_path=tmp_path / "twin.db",
        asr=ASRSettings(provider="command", command="unused"),
        # Uploads are admitted whatever the machine running the tests has free.
        library=LibrarySettings(headroom_gb=0),
        auth=AuthSettings(
            enabled=True,
            provider="sso",
            allowed_domains=["acme.cn"],
            admin_emails=["sso:9999"],
            sso=SSOSettings(me_url=login.url, cookie="sso", login_url="/login"),
        ),
    )
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        yield client
    login.server.shutdown()
    login.server.server_close()


def as_(web: TestClient, cookie: str) -> TestClient:
    web.cookies.set("sso", cookie)
    return web


def team_library(tmp_path: Path) -> Library:
    return Library(tmp_path / "library" / "team")


def uploaded(library: Library, recording_id: str, subject: str) -> str:
    library.update(recording_id, uploader=owner_key(f"sso:{subject}"))
    return recording_id


def meeting(library: Library, name: str = "2026-10-12 周一经营会.m4a", by: str = "2001") -> str:
    """王五 (2001) uploaded it. 张三 (S1) speaks long enough to become an unnamed person; 李总 (S2) is undecided;
    S3 says one word."""
    rec = recording(
        library,
        name,
        [
            Segment(start=0, end=6, text="续费方案我周四前给到大家。", speaker="S1"),
            Segment(start=6, end=10, text="我反对压缩研发。", speaker="S2"),
            Segment(start=10, end=16, text="先把老用户这块做透。", speaker="S1"),
            Segment(start=16, end=17, text="嗯。", speaker="S3"),
        ],
        [
            Speaker(id="S1", seconds=120, embedding=[1.0, 0.0, 0.0]),
            Speaker(id="S2", seconds=30, embedding=[0.0, 1.0, 0.0]),
            Speaker(id="S3", seconds=1, embedding=[0.95, 0.0, 0.3]),
        ],
    )
    playback = str(library.folder(rec) / "playback.flac")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=17", "-ar", "16000", "-ac", "1", playback],
        check=True,
    )
    Team(library).classify(rec)
    return uploaded(library, rec, by)


def sentence(seconds: float = 6) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        frames = (int(8000 * math.sin(2 * math.pi * 220 * i / 16000)) for i in range(int(seconds * 16000)))
        wav.writeframes(b"".join(f.to_bytes(2, "little", signed=True) for f in frames))
    return buffer.getvalue()


def enroll(web: TestClient) -> dict[str, Any]:
    put = web.put("/api/library/voice", files={"file": ("voice.webm", sentence())}, headers=CSRF)
    assert put.status_code == 200, put.text
    return dict(put.json())


def open_twin(web: TestClient, persona_id: str) -> bool:
    return web.get("/api/status", headers={"X-Twin-Persona": persona_id}).json().get("memory_updating") is False


def test_a_colleague_hears_one_sentence_says_it_is_them_and_the_twin_is_theirs(web: TestClient, tmp_path: Path) -> None:
    library = team_library(tmp_path)
    rec = meeting(library)
    [unnamed] = Team(library).people()
    assert unnamed.auto

    before = as_(web, MEMBER).get("/api/library/voice").json()
    assert before == {"available": True, "enrolled": False, "items": [], "persona_id": None}
    state = enroll(web)
    assert state["enrolled"] is True
    [offer] = state["items"]
    # One sentence, its five seconds, the meeting's title and date: nothing that leads into the recording.
    assert set(offer) == {"id", "state", "quote", "title", "date", "more", "unsure", "sample_url"}
    assert offer["state"] == "offered" and offer["quote"] == "续费方案我周四前给到大家。"
    assert offer["title"] == "2026-10-12 周一经营会" and offer["date"] == "2026-10-12"
    assert offer["unsure"] is False and offer["more"] == 0
    assert rec not in str(state) and "王五" not in str(state) and "反对" not in str(state)
    sample = web.get(offer["sample_url"])
    assert sample.status_code == 200 and sample.headers["content-type"] == "audio/wav"
    for forged in (rec, f"{rec}/S2", "vo_0000000000000000"):
        assert web.get(f"/api/library/voice/items/{forged}/sample").status_code == 404
    # Until they say it is them, nothing of the recording is theirs to see.
    assert web.get(f"/api/library/recordings/{rec}").status_code == 404
    assert web.get("/api/library").json()["recordings"] == []
    assert not list((tmp_path / "library" / "team" / "members" / owner_key("sso:2002")).glob("*.wav"))

    confirmed = web.post(f"/api/library/voice/offers/{offer['id']}", json={"verdict": "me"}, headers=CSRF).json()
    [mine] = confirmed["items"]
    assert mine["state"] == "mine"
    pid = confirmed["persona_id"]
    [twin] = web.get("/api/personas").json()
    assert twin["id"] == pid and twin["name"] == "张三"
    assert twin["mine"] is True and twin["from_meetings"] is True and twin["approved"] is False
    assert twin["owner"] == "sso:2002" and twin["public"] is False

    # Written back to the uploader's library, as a decision with a voice sample.
    people = {p.name: p for p in Team(library).people()}
    assert set(people) == {"张三"} and people["张三"].persona_id == pid and people["张三"].samples == 1
    view = {s.id: s for s in Team(library).speakers(library.get(rec))}  # type: ignore[arg-type]
    assert view["S1"].decision == "confirmed" and not view["S1"].auto and view["S2"].decision == "none"
    until(lambda: open_twin(web, pid))
    with PersonaStore(tmp_path / "personas" / pid / "twin.db") as store:
        own = [e.text for e in store.list_expressions() if e.is_target]
    assert own == ["[00:00] 续费方案我周四前给到大家。", "[00:10] 先把老用户这块做透。"]

    # Now one of the people of that meeting, 张三 may read and hear it, but deciding about it stays the uploader's.
    detail = web.get(f"/api/library/recordings/{rec}").json()
    assert detail["can_edit"] is False and detail["mine"] == ["S1"]
    assert all("candidates" not in s for s in detail["speakers"])
    assert [r["id"] for r in web.get("/api/library").json()["recordings"]] == [rec]
    assert web.get(f"/api/library/recordings/{rec}/speakers/S1/samples/0").status_code == 200
    put = web.put(
        f"/api/library/recordings/{rec}/speakers/S2",
        json={"transcript_id": detail["transcript_id"], "revision": detail["revision"], "action": "unknown"},
        headers=CSRF,
    )
    assert put.status_code == 403

    # The uploader sees who it is, but the twin is not theirs to open, rename or dress.
    look = twin["avatar_preset"]
    uploader = as_(web, UPLOADER)
    [person] = uploader.get("/api/library/people").json()["items"]
    assert person["name"] == "张三" and person["self_claimed"] is True and person["persona_id"] is None
    assert uploader.get("/api/personas").json() == []
    assert person["twin_id"] is None  # not in their list of twins either, so no second row to tell apart
    assert uploader.get("/api/persona/state", headers={"X-Twin-Persona": pid}).status_code == 404
    assert uploader.post(f"/api/library/people/{person['id']}/persona", headers=CSRF).status_code == 409
    renamed = uploader.patch(f"/api/library/people/{person['id']}", json={"name": "张三丰", "gender": "male"})
    assert renamed.status_code == 403  # no X-Twin
    assert uploader.patch(
        f"/api/library/people/{person['id']}", json={"name": "张三丰", "gender": "male"}, headers=CSRF
    ).json() == {"updated": True}
    as_(web, MEMBER)
    [twin] = web.get("/api/personas").json()
    assert twin["name"] == "张三" and twin["avatar_preset"] == look
    # Their own twin is in their list of twins; the person row names it, though it is theirs only by voice.
    [mine] = [p for p in web.get("/api/library/people").json()["items"] if p["name"] == "张三丰"]
    assert (mine["self_claimed"], mine["persona_id"], mine["talk"], mine["twin_id"]) == (True, None, None, pid)

    # Only once 张三 says it is all right do colleagues get to ask it.
    approved = web.post(f"/api/personas/{pid}/approve", json={"public": True}, headers=CSRF).json()
    assert approved["approved"] is True and approved["public"] is True
    assert [p["id"] for p in as_(web, OTHER).get("/api/personas").json()] == [pid]


def test_taking_back_clears_the_voice_and_it_is_not_offered_again(web: TestClient, tmp_path: Path) -> None:
    library = team_library(tmp_path)
    rec = meeting(library)
    as_(web, MEMBER)
    [offer] = enroll(web)["items"]
    confirmed = web.post(f"/api/library/voice/offers/{offer['id']}", json={"verdict": "me"}, headers=CSRF).json()
    [mine] = confirmed["items"]
    back = web.delete(f"/api/library/voice/claims/{mine['id']}", headers=CSRF)
    assert back.status_code == 200 and back.json()["items"] == []
    view = {s.id: s for s in Team(library).speakers(library.get(rec))}  # type: ignore[arg-type]
    assert view["S1"].decision == "none"
    assert web.get("/api/library/voice").json()["items"] == []


def test_not_me_is_kept_to_oneself_and_the_same_meeting_is_offered_once(web: TestClient, tmp_path: Path) -> None:
    first = second = team_library(tmp_path)
    meeting(first)
    # 赵六 uploaded another meeting where 张三's voice is less sure, and nobody has said who anyone is.
    rec = recording(
        second,
        "季度复盘.m4a",
        [Segment(start=0, end=8, text="我同意，先上灰度。", speaker="S1")],
        [Speaker(id="S1", seconds=8, embedding=[0.4, 0.6, 0.6])],
    )
    uploaded(second, rec, "2003")
    as_(web, MEMBER)
    offers = enroll(web)["items"]
    assert [o["quote"] for o in offers] == ["续费方案我周四前给到大家。", "我同意，先上灰度。"]
    assert offers[1]["unsure"] is True and offers[1]["date"] is None
    after = web.post(f"/api/library/voice/offers/{offers[1]['id']}", json={"verdict": "not"}, headers=CSRF).json()
    assert [o["quote"] for o in after["items"]] == ["续费方案我周四前给到大家。"]
    assert Team(second).speakers(second.get(rec))[0].decision == "none"  # type: ignore[arg-type]
    assert (
        web.post(f"/api/library/voice/offers/{offers[1]['id']}", json={"verdict": "me"}, headers=CSRF).status_code
        == 404
    )


def test_a_voice_the_uploader_settled_meanwhile_is_refused(web: TestClient, tmp_path: Path) -> None:
    library = team_library(tmp_path)
    rec = meeting(library)
    as_(web, MEMBER)
    [offer] = enroll(web)["items"]
    team = Team(library)
    found = library.get(rec)
    assert found and found.transcript_id
    li = team.add_person("李总")
    [unnamed] = [p for p in team.people() if p.auto]
    team.resolve(unnamed.id, li.id)
    late = web.post(f"/api/library/voice/offers/{offer['id']}", json={"verdict": "me"}, headers=CSRF)
    assert late.status_code == 409 and "刷新" in late.json()["detail"]
    assert {p.name for p in team.people()} == {"李总"} and web.get("/api/personas").json() == []


def test_without_a_work_address_or_a_voiceprint_there_is_nothing_to_find(web: TestClient, tmp_path: Path) -> None:
    meeting(team_library(tmp_path))
    assert as_(web, NO_ADDRESS).get("/api/library/voice").status_code == 404
    as_(web, MEMBER)
    short = web.put("/api/library/voice", files={"file": ("voice.webm", sentence(2))}, headers=CSRF)
    assert short.status_code == 400 and "太短" in short.json()["detail"]
    FakeVoice.print = None
    old = web.put("/api/library/voice", files={"file": ("voice.webm", sentence())}, headers=CSRF)
    assert old.status_code == 503 and "声纹" in old.json()["detail"]
    FakeVoice.print = ZHANG
    assert enroll(web)["items"]
    forgotten = web.delete("/api/library/voice", headers=CSRF).json()
    assert forgotten["enrolled"] is False and forgotten["items"] == []
