"""Meeting transcripts brought into the team's library as text: a recording with no sound and no voiceprints, whose
speakers are told apart by the names the export writes, and which feeds the twins of the members in it like any
meeting."""

from __future__ import annotations

import datetime as dt
import json
from collections import namedtuple
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from twin.config import LibrarySettings, Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media.library import Library
from twin.media.review import Reviews
from twin.media.team import Team
from twin.persona.schema import SourceKind
from twin.web import create_app
from twin.web.library import parsed_source

HEADERS = {"X-Twin": "1"}

# The way 飞书妙记, 通义听悟 and 腾讯会议 write a transcript out: a speaker and the time they began, then their words.
EXPORT = """运营周会

林舟 00:00:03
大家好，今天过一下渠道数据。
许清禾 00:00:20
我这边周三前补齐。
说话人 3 00:01:10
下周把渠道数据拉一下
林舟 00:01:40
好的，那这件事就交给说话人 3。
Kevin 00:02:05
合同这周能签吗
林舟 00:02:30
我周五前给您答复。
说话人 3 00:03:00
收到
"""
PLAIN = "林舟：开始吧\n许清禾：好\n说话人 1：嗯\n林舟：继续\n"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    # No headroom asked of the test machine's disk; ``test_a_transcript_is_refused_like_an_upload`` sets it.
    settings = Settings(db_path=tmp_path / "twin.db", library=LibrarySettings(headroom_gb=0))
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def team_of(tmp_path: Path) -> Team:
    return Team(Library(tmp_path / "library" / "team"))


def preview(client: TestClient, name: str, text: str) -> Any:
    return client.post(
        "/api/library/transcripts/preview", headers=HEADERS, files={"file": (name, text.encode(), "text/plain")}
    )


def bring_in(client: TestClient, name: str, text: str, body: dict[str, Any] | None = None) -> Any:
    return client.post(
        "/api/library/transcripts",
        headers=HEADERS,
        files={"file": (name, text.encode(), "text/plain")},
        data={"payload": json.dumps(body or {})},
    )


def test_the_preview_says_who_each_speaker_would_be_and_stores_nothing(client: TestClient, tmp_path: Path) -> None:
    team = team_of(tmp_path)
    lin = team.add_person("林舟")
    team.add_person("许清禾")
    shown = preview(client, "运营周会-2026-10-18.txt", EXPORT)
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert (body["title"], body["date"], body["turns"], body["minutes"]) == ("运营周会-2026-10-18", "2026-10-18", 7, 3)
    by_label = {s["label"]: s for s in body["speakers"]}
    assert [s["label"] for s in body["speakers"]] == ["林舟", "说话人 3", "Kevin", "许清禾"]  # the most said first
    assert by_label["林舟"]["segments"] == 3 and by_label["林舟"]["person"] == {"id": lin.id, "name": "林舟"}
    assert by_label["许清禾"]["person"]["name"] == "许清禾"
    # A label that names nobody is shown with a line of what it said; so is a name nobody in the team has.
    assert by_label["说话人 3"]["generic"] and by_label["说话人 3"]["person"] is None
    assert by_label["说话人 3"]["sample"] == "下周把渠道数据拉一下" and by_label["说话人 3"]["segments"] == 2
    assert by_label["Kevin"]["person"] is None and not by_label["Kevin"]["generic"]
    assert client.get("/api/library").json()["recordings"] == []
    # Not a transcript: a text without turns, a file type that holds no text.
    assert preview(client, "说明.txt", "只是一段说明文字。\n没有人在说话。").status_code == 400
    assert preview(client, "录音.m4a", "x").status_code == 400


def test_an_export_brought_in_gives_speakers_named_for_members_to_them_and_the_chosen_to_the_chosen(
    client: TestClient, tmp_path: Path
) -> None:
    team = team_of(tmp_path)
    lin, xu, zhou = (team.add_person(name) for name in ("林舟", "许清禾", "周石言"))
    done = bring_in(
        client,
        "运营周会.txt",
        EXPORT,
        {
            "title": "运营周会 10月18日",
            "date": "2026-10-18",
            "speakers": {"说话人 3": {"person_id": zhou.id}, "Kevin": {"outsider": True}},
        },
    )
    assert done.status_code == 201, done.text
    made = done.json()
    assert made["new"] is True and made["kind"] == "transcript" and made["status"] == "ready"
    assert (made["decided"], made["unsettled"]) == (4, 0)
    assert made["filename"] == "运营周会 10月18日.txt" and made["speakers"] == 4 and made["segments"] == 7

    listed = {r["id"]: r for r in client.get("/api/library").json()["recordings"]}
    row = listed[made["id"]]
    # It reads as a recording that is done: nothing to transcribe, proofread or name, and nobody left to settle.
    assert row["people"] == ["林舟", "许清禾", "周石言"] and row["unsettled"] == 0 and row["proofread"] == ""
    assert row["duration_s"] == pytest.approx(177.5, abs=0.1)

    recording = team.library.get(made["id"])
    assert recording is not None and recording.proofread == recording.transcript_id == recording.named
    seen = {s.id: (s.decision, s.person_id, s.auto) for s in team.speakers(recording)}
    assert seen == {
        "林舟": ("confirmed", lin.id, False),
        "许清禾": ("confirmed", xu.id, False),
        "说话人 3": ("confirmed", zhou.id, False),
        "Kevin": ("unknown", None, False),
    }
    # Said by the member it was given to, in the order it was said, with the time it was said at.
    source = next(s for s in team.sources(zhou.id, "周石言"))
    assert source.kind == "transcript" and source.date == "2026-10-18"
    assert [line for line in source.lines if line[2]] == [
        ("周石言", "[01:07] 下周把渠道数据拉一下", True),
        ("周石言", "[02:57] 收到", True),
    ]
    assert ("林舟", "[00:00] 大家好，今天过一下渠道数据。", False) in source.lines
    # The twin is built from it like from a meeting: the person's own lines are theirs, the meeting is dated.
    kept = parsed_source(source)
    assert kept.source.kind is SourceKind.AUDIO and kept.source.first_date == dt.date(2026, 10, 18)
    assert (kept.source.n_expressions, kept.source.n_target) == (7, 2)
    assert ("其他人1", "[02:02] 合同这周能签吗", False) in source.lines

    # No sound: nothing to hear, nothing to hear again, nothing to transcribe again.
    assert client.get(f"/api/library/recordings/{made['id']}/speakers/林舟/samples/0").status_code == 404
    detail = client.get(f"/api/library/recordings/{made['id']}").json()
    assert detail["timed"] is True and {s["samples"] for s in detail["speakers"]} == {0}
    assert team.library.recollectable() == () and team.library.unproofread() == ()
    assert Reviews(team.library).waiting() == []

    # The same file again, under another name, is the recording there is.
    again = bring_in(client, "改名了.txt", EXPORT)
    assert again.status_code == 201 and again.json()["new"] is False and again.json()["id"] == made["id"]
    assert len(client.get("/api/library").json()["recordings"]) == 1


def test_a_speaker_nobody_chose_is_given_to_the_member_of_that_name_or_waits(
    client: TestClient, tmp_path: Path
) -> None:
    team = team_of(tmp_path)
    lin = team.add_person("林舟")
    team.add_person("许清禾")
    made = bring_in(client, "站会.txt", PLAIN).json()
    # The two members are found by their names; 说话人 1 names no one, so it waits like any speaker nobody settled.
    assert (made["decided"], made["unsettled"]) == (2, 1)
    recording = team.library.get(made["id"])
    assert recording is not None
    seen = {s.id: (s.decision, s.person_id) for s in team.speakers(recording)}
    assert seen["林舟"] == ("confirmed", lin.id) and seen["说话人 1"] == ("none", None)
    waiting = [(r.id, n) for r, n in team.unvoiced()]
    assert waiting == [(recording.id, 1)]
    row = next(r for r in client.get("/api/library").json()["recordings"] if r["id"] == recording.id)
    assert row["unsettled"] == 1
    # No times in this one: its segments sit at 0, and its lines carry no clock.
    assert recording.duration_s is None
    lines = next(s for s in team.sources(lin.id, "林舟")).lines
    assert lines[0] == ("林舟", "开始吧", True)
    # It is settled in the recording itself, by name, like a speaker whose voice matched nobody.
    detail = client.get(f"/api/library/recordings/{recording.id}").json()
    assert detail["timed"] is False
    chosen = client.put(
        f"/api/library/recordings/{recording.id}/speakers/说话人 1",
        headers=HEADERS,
        json={
            "transcript_id": detail["transcript_id"],
            "revision": detail["revision"],
            "action": "unknown",
        },
    )
    assert chosen.status_code == 200, chosen.text
    assert team.unvoiced() == []


def test_a_member_chosen_for_a_label_overrides_the_name_and_an_unknown_one_is_refused(
    client: TestClient, tmp_path: Path
) -> None:
    team = team_of(tmp_path)
    team.add_person("林舟")
    xu = team.add_person("许清禾")
    refused = bring_in(client, "站会.txt", PLAIN, {"speakers": {"林舟": {"person_id": "per_nobody"}}})
    assert refused.status_code == 400
    assert bring_in(client, "站会.txt", PLAIN, {"speakers": {"没有这个人": {"outsider": True}}}).status_code == 400
    assert client.get("/api/library").json()["recordings"] == []
    # 林舟's lines are given to 许清禾 by the importer's choice; 许清禾 is left to wait (an empty choice).
    made = bring_in(client, "站会.txt", PLAIN, {"speakers": {"林舟": {"person_id": xu.id}, "许清禾": {}}}).json()
    recording = team.library.get(made["id"])
    assert recording is not None
    seen = {s.id: (s.decision, s.person_id) for s in team.speakers(recording)}
    assert seen["林舟"] == ("confirmed", xu.id) and seen["许清禾"] == ("none", None)


def test_a_transcript_is_refused_like_an_upload_when_the_disk_or_the_queue_is_full(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("twin.web.library.shutil.disk_usage", lambda _: usage(100, 90, 10))
    refused = bring_in(client, "站会.txt", PLAIN)
    assert refused.status_code == 507 and "磁盘空间不足" in refused.json()["detail"]
    monkeypatch.setattr("twin.web.library.shutil.disk_usage", lambda _: usage(10**12, 0, 10**12))
    monkeypatch.setattr("twin.media.library.Library.pending", lambda *_: 20)  # the member's queue is full
    full = bring_in(client, "站会.txt", PLAIN)
    assert full.status_code == 409 and "排队" in full.json()["detail"]
    assert client.get("/api/library").json()["recordings"] == []
    monkeypatch.setattr("twin.media.library.Library.pending", lambda *_: 0)
    assert bring_in(client, "站会.txt", PLAIN).status_code == 201
