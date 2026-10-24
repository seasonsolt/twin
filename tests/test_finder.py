"""Finding out who knows about a matter: a question put to the whole team, answered with the people to ask.

Only what colleagues may use counts; the one who asks, a twin nobody took, one not open to colleagues and one that holds
nothing about the matter are never recommended; people are ordered by how well they know it, then by on how many
occasions and how recently. The cache of how well each knows each facet is made again when their memories change."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from teamkit import ADMIN, CSRF, Team, TopicEmbedder, Twin, item, make_web

from twin.config import Settings
from twin.finder import Finder, TwinRef, asks_for_decision, coverage_rows, eligible, refresh_coverage
from twin.media.library import TEAM, Cleaned
from twin.persona.chat import index_persona
from twin.persona.items import PersonaItem
from twin.persona.store import PersonaStore
from twin.teamdb import TeamDB

QUESTION = "续约折扣谁能批？"
MATTER = "续约折扣 15% 以内销售负责人自己定"
OTHER = "周报按项目写"


def make_twin(
    root: Path,
    key: str,
    items: list[PersonaItem],
    *,
    member: str | None = None,
    public: bool = True,
    embedder: TopicEmbedder | None = None,
) -> TwinRef:
    """A twin database holding ``items`` with their vectors, as the finder is given one."""
    path = root / key / "twin.db"
    path.parent.mkdir(parents=True)
    with PersonaStore(path) as store:
        store.set_meta("built_at", "2026-01-01")
        for facet in sorted({i.facet_id for i in items}):
            store.replace_facet_items(facet, [i for i in items if i.facet_id == facet])
        index_persona(store, embedder or TopicEmbedder(), Settings(db_path=path))
    return TwinRef(key, f"名{key}", path, member if member is not None else f"{key}@xjjk.com", public)


@pytest.fixture
def team(tmp_path: Path) -> Iterator[TeamDB]:
    with TeamDB(tmp_path / "team" / "team.db") as db:
        yield db


def names(found: list[dict[str, Any]]) -> list[str]:
    return [row["persona_id"] for row in found]


def test_people_are_ordered_by_how_well_they_know_it_then_occasions_then_how_recently(
    tmp_path: Path, team: TeamDB
) -> None:
    twins = [
        make_twin(tmp_path, "wang", [item("a", "5.2", MATTER, sources=4, behavior=True)]),  # a good deal (3)
        make_twin(tmp_path, "shen", [item("b", "5.2", MATTER, sources=2, day="2026-09-01")]),  # some (2), 2 occasions
        make_twin(tmp_path, "li", [item("c", "5.2", MATTER, sources=3, day="2026-10-01")]),  # some, 3, newer
        make_twin(tmp_path, "zhou", [item("d", "5.2", MATTER, sources=3, day="2026-08-01")]),  # some, 3, older
        make_twin(tmp_path, "kai", [item("e", "5.2", MATTER, sources=2, day="2026-10-10")]),  # some, 2, newest
        make_twin(tmp_path, "chen", [item("f", "5.2", MATTER, sources=1, own_words=False)]),  # only mentioned (1)
    ]
    found = Finder(team).recommend(QUESTION, TopicEmbedder(), twins, "asker@xjjk.com", limit=10)
    assert names(found) == ["wang", "li", "zhou", "kai", "shen", "chen"]
    first = found[0]
    assert (first["level"], first["label"], first["occasions"]) == (3, "了解较多", 4)
    assert first["facets"] == ["熟悉领域的看法"] and first["last_seen"] == "2026-09-04"
    assert {row["persona_id"]: row["label"] for row in found}["chen"] == "提到过"
    # No score is shown or kept, and at most three are recommended.
    assert all(
        set(row) == {"persona_id", "name", "level", "label", "occasions", "last_seen", "facets"} for row in found
    )
    assert len(Finder(team).recommend(QUESTION, TopicEmbedder(), twins, "asker@xjjk.com")) == 3


def test_the_one_who_asks_unclaimed_and_closed_twins_and_those_with_nothing_are_never_recommended(
    tmp_path: Path, team: TeamDB
) -> None:
    held = [item("a", "5.2", MATTER, sources=3)]
    twins = [
        make_twin(tmp_path, "wang", held, member="wang@xjjk.com"),
        make_twin(tmp_path, "shen", held, member="shen@xjjk.com"),
        make_twin(tmp_path, "nobody", held, member=""),  # not taken by anyone
        make_twin(tmp_path, "closed", held, member="closed@xjjk.com", public=False),  # not open to colleagues
        make_twin(tmp_path, "else", [item("z", "5.2", OTHER, sources=3)], member="else@xjjk.com"),  # another matter
        make_twin(tmp_path, "empty", [], member="empty@xjjk.com"),
    ]
    twins[2] = TwinRef(twins[2].persona_id, twins[2].name, twins[2].path, None, True)
    finder = Finder(team)
    # (Alike in everything, they come in the order of their ids.)
    assert names(finder.recommend(QUESTION, TopicEmbedder(), twins, "xu@xjjk.com", limit=10)) == ["shen", "wang"]
    # Whoever asks is left out of their own answer; nobody is left to recommend when it is the only one who knows.
    assert names(finder.recommend(QUESTION, TopicEmbedder(), twins, "wang@xjjk.com", limit=10)) == ["shen"]
    assert not any(eligible(t, "xu@xjjk.com") for t in twins[2:4])
    assert not eligible(twins[0], "wang@xjjk.com")
    # Nothing known of the matter: nobody. A question with nothing to go by asks nobody.
    assert finder.recommend("明天中午吃什么", TopicEmbedder(), twins, "xu@xjjk.com") == []
    assert finder.recommend("  ", TopicEmbedder(), twins, "xu@xjjk.com") == []


def test_what_only_the_person_may_use_is_neither_found_nor_counted(tmp_path: Path, team: TeamDB) -> None:
    kept = item("k", "5.2", MATTER, sources=4, behavior=True)  # would be a good deal, if it counted
    twins = [make_twin(tmp_path, "wang", [kept], member="wang@xjjk.com")]
    private = item("p", "1.3", "续约折扣的老故事", sources=3)  # a facet that starts as theirs alone
    twins.append(make_twin(tmp_path, "shen", [private], member="shen@xjjk.com"))
    finder = Finder(team)
    assert names(finder.recommend(QUESTION, TopicEmbedder(), twins, "xu@xjjk.com")) == ["wang"]
    # The person keeps their item to themself: the next question no longer finds them, with no refresh asked for.
    with PersonaStore(twins[0].path) as store:
        store.set_item_tier("k", "self")
    assert finder.recommend(QUESTION, TopicEmbedder(), twins, "xu@xjjk.com") == []
    assert team.coverage(["wang"]) == []
    # And back: found again, as what they now allow.
    with PersonaStore(twins[0].path) as store:
        store.set_item_tier("k", "colleague")
    assert names(finder.recommend(QUESTION, TopicEmbedder(), twins, "xu@xjjk.com")) == ["wang"]
    # The person opening a private item up makes it count.
    with PersonaStore(twins[1].path) as store:
        store.set_item_tier("p", "colleague")
    assert names(finder.recommend(QUESTION, TopicEmbedder(), twins, "xu@xjjk.com")) == ["wang", "shen"]


def test_the_cache_of_what_each_twin_knows_is_kept_in_the_team_database_and_can_be_dropped_and_made_again(
    tmp_path: Path, team: TeamDB
) -> None:
    twin = make_twin(tmp_path, "wang", [item("a", "5.2", MATTER, sources=3), item("b", "1.3", "私事", sources=3)])
    with PersonaStore(twin.path) as store:
        rows = coverage_rows("wang", store, dt.datetime(2026, 10, 22, tzinfo=dt.UTC))
        # Only the facet colleagues may use is counted: 1.3 is the person's own by default.
        assert [(r.facet_id, r.level, r.occasions, r.last_seen) for r in rows] == [("5.2", 2, 3, "2026-09-03")]
        assert refresh_coverage(team, "wang", store) == 1
    [row] = team.coverage()
    assert (row.persona_id, row.facet_id, row.level, row.kernel) == ("wang", "5.2", 2, "persona-v7/v2")
    # The cache is only a cache: dropped, the next question makes it again.
    team.forget_coverage()
    assert team.coverage() == []
    assert names(Finder(team).recommend(QUESTION, TopicEmbedder(), [twin], "xu@xjjk.com")) == ["wang"]
    assert [r.persona_id for r in team.coverage()] == ["wang"]
    # And a twin gone for good takes its rows with it.
    team.forget_persona("wang")
    assert team.coverage() == []


def test_a_twin_whose_memory_is_being_rebuilt_from_changed_recordings_is_left_out_until_it_is_done(
    tmp_path: Path, team: TeamDB
) -> None:
    from twin.persona import gate

    twin = make_twin(tmp_path, "wang", [item("a", "5.2", MATTER, sources=3)])
    finder = Finder(team)
    assert names(finder.recommend(QUESTION, TopicEmbedder(), [twin], "xu@xjjk.com")) == ["wang"]

    def updating(_: Path) -> int:
        raise gate.MemoryUpdating

    original = gate.version_at
    gate.version_at = updating  # type: ignore[assignment]
    try:
        assert finder.recommend(QUESTION, TopicEmbedder(), [twin], "xu@xjjk.com") == []
    finally:
        gate.version_at = original
    assert names(finder.recommend(QUESTION, TopicEmbedder(), [twin], "xu@xjjk.com")) == ["wang"]


def test_vectors_of_another_model_are_not_compared_and_a_changed_database_is_read_again(
    tmp_path: Path, team: TeamDB
) -> None:
    twin = make_twin(tmp_path, "wang", [item("a", "5.2", MATTER, sources=3)])
    finder = Finder(team)

    class Elsewhere(TopicEmbedder):
        name = "elsewhere"

    assert finder.recommend(QUESTION, Elsewhere(), [twin], "xu@xjjk.com") == []
    # The vectors are held in memory while the twin's items are as they were, and read again when they are not.
    embedder = TopicEmbedder()
    assert names(finder.recommend(QUESTION, embedder, [twin], "xu@xjjk.com")) == ["wang"]
    with sqlite3.connect(twin.path) as raw:
        raw.execute("DELETE FROM p_items")
    assert finder.recommend(QUESTION, embedder, [twin], "xu@xjjk.com") == []


def test_a_question_that_asks_for_a_decision_is_told_so() -> None:
    assert asks_for_decision("超过 15% 的折扣你来定吗？")
    assert not asks_for_decision(QUESTION)


# ------------------------------------------------------------------ the question from anywhere


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Team]:
    yield from make_web(tmp_path, monkeypatch)


def team_of_four(web: Team) -> dict[str, Twin]:
    held = [item("pi_x", "5.2", MATTER, sources=4, behavior=True)]
    twins = {
        "wang": web.add_twin("wang", "wang@xjjk.com", "王屿", items=held),
        "shen": web.add_twin("shen", "shen@xjjk.com", "沈从", items=[item("pi_y", "5.2", MATTER, sources=2)]),
        "chen": web.add_twin("chen", "chen@xjjk.com", "陈一", items=[item("pi_z", "5.2", OTHER, sources=3)]),
        "unclaimed": web.add_twin(
            "unclaimed", "u@xjjk.com", "未认领", items=[item("pi_u", "5.2", MATTER, sources=4)], take=False
        ),
    }
    for twin in twins.values():
        web.index_items(twin)
    return twins


def ask(web: Team, who: str, question: str) -> dict[str, Any]:
    web.as_(who)
    response = web.web.get("/api/personas/ask", params={"q": question}, headers=CSRF)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_the_question_gives_the_people_to_ask_without_the_asker_unclaimed_twins_or_those_who_know_nothing(
    web: Team,
) -> None:
    twins = team_of_four(web)
    found = ask(web, "xu@xjjk.com", QUESTION)
    assert [row["name"] for row in found["people"]] == ["王屿", "沈从"]
    assert [row["label"] for row in found["people"]] == ["了解较多", "了解一些"]
    assert [row["persona_id"] for row in found["people"]] == [twins["wang"].persona, twins["shen"].persona]
    assert found["degraded"] is False and found["decision"] is False and found["team_answers"] == []
    # The one who knows most is not told of themself.
    assert [row["name"] for row in ask(web, "wang@xjjk.com", QUESTION)["people"]] == ["沈从"]
    # Nobody, administrator or not, is recommended a twin nobody took.
    assert twins["unclaimed"].persona not in [r["persona_id"] for r in ask(web, ADMIN, QUESTION)["people"]]
    # A matter nobody has talked about.
    assert ask(web, "xu@xjjk.com", "年会在哪办")["people"] == []
    assert ask(web, "xu@xjjk.com", "要不要拍板批准这个折扣")["decision"] is True


def test_a_twin_closed_to_colleagues_is_not_recommended_until_it_is_opened(web: Team) -> None:
    twins = team_of_four(web)
    web.as_("shen@xjjk.com")
    closed = web.web.post(f"/api/personas/{twins['shen'].persona}/approve", json={"public": False}, headers=CSRF)
    assert closed.status_code == 200
    assert [row["name"] for row in ask(web, "xu@xjjk.com", QUESTION)["people"]] == ["王屿"]
    web.as_("shen@xjjk.com")
    web.web.post(f"/api/personas/{twins['shen'].persona}/approve", json={"public": True}, headers=CSRF)
    assert [row["name"] for row in ask(web, "xu@xjjk.com", QUESTION)["people"]] == ["王屿", "沈从"]


def test_the_question_needs_signing_in_and_something_to_ask(web: Team) -> None:
    team_of_four(web)
    web.web.cookies.clear()
    assert web.web.get("/api/personas/ask", params={"q": QUESTION}, headers=CSRF).status_code == 401
    web.as_("xu@xjjk.com")
    assert web.web.get("/api/personas/ask", params={"q": "好"}, headers=CSRF).status_code == 400
    assert web.web.get("/api/personas/ask", headers=CSRF).status_code == 400


def test_without_the_embedding_model_the_meetings_are_still_found_by_words(web: Team) -> None:
    team_of_four(web)
    web.as_(ADMIN)
    imported = web.web.post(
        "/api/library/transcripts",
        headers=CSRF,
        files={
            "file": (
                "经营会.txt",
                "王屿：超过 15% 的续约折扣都报给我\n沈从：当天给答复\n王屿：好的\n沈从：继续\n".encode(),
                "text/plain",
            )
        },
        data={"payload": json.dumps({"title": "经营会", "date": "2026-10-09"})},
    )
    assert imported.status_code == 201, imported.text

    def down(_: list[str]) -> None:
        from twin.embed import EmbedError

        raise EmbedError("down")

    web.embedder.embed = down  # type: ignore[assignment,method-assign]
    found = ask(web, ADMIN, "续约折扣超过 15% 怎么办")
    assert found["degraded"] is True and found["people"] == [] and found["team_answers"] == []
    [meeting] = found["meetings"]
    assert meeting["title"] == "经营会" and meeting["date"] == "2026-10-09"
    assert "15%" in meeting["quote"] and meeting["recording_id"]
    # Where in the recording's transcript, as its page lists the lines, to open it on.
    detail = web.web.get(f"/api/library/recordings/{meeting['recording_id']}")
    assert detail.json()["segments"][meeting["line"]]["text"].startswith("超过 15%")
    # Only the meetings the asker may read: someone not in it and not its uploader finds nothing.
    assert ask(web, "xu@xjjk.com", "续约折扣超过 15% 怎么办")["meetings"] == []


def test_a_recording_proofread_after_it_was_searched_is_found_and_quoted_as_proofread(web: Team) -> None:
    team_of_four(web)
    web.as_(ADMIN)
    imported = web.web.post(
        "/api/library/transcripts",
        headers=CSRF,
        files={
            "file": (
                "经营会.txt",
                "王屿：超过 15% 的续约折扣都报给我\n沈从：当天给答复\n王屿：好的\n沈从：继续\n".encode(),
                "text/plain",
            )
        },
        data={"payload": json.dumps({"title": "经营会", "date": "2026-10-09"})},
    )
    assert imported.status_code == 201, imported.text
    [before] = ask(web, ADMIN, "续约折扣超过 15% 怎么办")["meetings"]
    assert "折扣" in before["quote"]
    # The proofreading is filed under the same transcript: the words change, the id does not.
    library = web.web.app.state.libraries.library(TEAM)  # type: ignore[attr-defined]
    recording = library.get(before["recording_id"])
    transcript = library.transcript(recording)
    assert recording is not None and transcript is not None
    corrected = [s.model_copy(update={"text": s.text.replace("折扣", "优惠")}) for s in transcript.segments]
    cleaned = Cleaned(transcript_id=transcript.id, created_at="2026-10-10", segments=corrected)
    assert library.write_cleaned(recording, cleaned)
    [after] = ask(web, ADMIN, "续约折扣超过 15% 怎么办")["meetings"]
    assert "优惠" in after["quote"] and "折扣" not in after["quote"]


@pytest.mark.parametrize(
    "question",
    [
        "你之前给我发的那份文档在哪",
        "能给我一个例子吗",
        "你定期开周会吗",
        "这个方案保证质量的关键是什么",
        "commitment 这个词什么意思",
        "我们组的 approver 是谁",
        "上周五前给我们讲的那个流程是什么",
    ],
)
def test_ordinary_questions_with_a_word_that_is_a_cue_in_another_sense_do_not_ask_for_the_persons_say(
    question: str,
) -> None:
    assert asks_for_decision(question) is False


@pytest.mark.parametrize(
    "question",
    [
        "周五前给我一版发布方案",
        "你能保证周五交付吗",
        "这个你定吧",
        "你答应吗",
        "please approve the discount",
        "要不要拍板批准这个折扣",
    ],
)
def test_a_request_for_a_promise_a_decision_or_a_straight_answer_does(question: str) -> None:
    assert asks_for_decision(question) is True
