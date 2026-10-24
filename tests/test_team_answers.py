"""Team answers: the person's reply to a question several people asked, made the team's.

The same matter asked by several people shows as one card on the person's page (nothing about the handoffs changes);
one reply goes to each asker's own conversation; the person may make it a team answer, which every twin then quotes
as it stands, as a card of its own; if the person says something else later it is shown as possibly out of date; once
withdrawn it is not quoted any more."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from teamkit import ADMIN, CSRF, Team, TopicEmbedder, item, make_web

from twin.config import Settings
from twin.handoffs import HandoffDesk, HandoffRefused
from twin.persona.chat import index_persona
from twin.persona.sources import parse_note
from twin.persona.store import PersonaStore
from twin.teamanswers import TeamAnswers, cosine_groups, merge_groups, prompt_line
from twin.teamdb import Handoff, TeamDB

LIN = "lin@xjjk.com"
WANG = "wang@xjjk.com"
ASKERS = {"xu": "xu@xjjk.com", "chen": "chen@xjjk.com", "zhou": "zhou@xjjk.com"}
TEMPLATE = {
    "xu": "旧版 Word 模板导出，这次之后还支持吗？",
    "chen": "客户问旧模板还能不能导出，我该怎么回？",
    "zhou": "销售那边听说旧模板要停用了，是真的吗？",
}
REPORT = "周报按项目写还是按人写？"
ANSWER = "旧版 Word 模板支持到 12 月 31 日，之后导出只保留新模板。"
PLAN = {
    "模板": {
        "reply": "这个得问林舟。",
        "meta": {"owner_part": "decide", "owner_ask": "旧模板还支持吗", "mode": "abstain"},
    },
    REPORT: {"reply": "按项目。", "meta": {"owner_part": "decide", "owner_ask": "周报怎么写"}},
}


@pytest.fixture
def team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Team]:
    yield from make_web(tmp_path, monkeypatch, PLAN)


@pytest.fixture
def scene(team: Team) -> Team:
    team.add_twin("lin", LIN, "林舟")
    team.add_twin("wang", WANG, "王屿")
    return team


def handoff_count(team: Team) -> int:
    return len(team.team.handoffs())


def three_ask(scene: Team) -> dict[str, str]:
    """Three colleagues ask 林舟's twin the same matter in their own words; their conversations."""
    lin = scene.twins["lin"]
    return {who: scene.ask(ASKERS[who], lin, TEMPLATE[who])[0] for who in ("xu", "chen", "zhou")}


# ------------------------------------------------------------------ one matter, one card


def test_questions_that_mean_the_same_are_grouped_by_the_embedder_and_unrelated_ones_are_not() -> None:
    def handoff(n: int, question: str, kind: str = "decide", key: str = "") -> Handoff:
        return Handoff(
            id=f"h{n}",
            persona_id="p1",
            owner="lin",
            conversation_id=f"c{n}",
            turn=2,
            asker=f"a{n}",
            asker_name=f"人{n}",
            via="direct",
            kind=kind,  # type: ignore[arg-type]
            question=question,
            context="",
            ask="",
            commit_what="",
            commit_due=None,
            status="delivered",
            outcome=None,
            reply=None,
            reply_tier=None,
            reply_turn=None,
            ledger_id=None,
            group_key=key,
            created_at=f"2026-10-22T09:0{n}:00+00:00",
            expires_at="2026-10-29T09:00:00+00:00",
            replied_at=None,
        )

    pool = [
        handoff(1, TEMPLATE["xu"]),
        handoff(2, REPORT),
        handoff(3, TEMPLATE["chen"]),
        handoff(4, TEMPLATE["zhou"], kind="commit"),
        handoff(5, "排期延到几号？", key="same"),
        handoff(6, "脚本什么时候好？", key="same"),
    ]
    groups = [[h.id for h in g] for g in merge_groups(pool, TopicEmbedder())]
    # A promise is taken for each asker, so it is not merged; equal questions (same key) always are.
    assert groups == [["h1", "h3"], ["h2"], ["h5", "h6"]]
    # Without an embedder only the equal ones are one.
    assert [[h.id for h in g] for g in merge_groups(pool, None)] == [["h1"], ["h2"], ["h3"], ["h5", "h6"]]
    assert cosine_groups(np.zeros((0, 0), dtype=np.float32), 0.5) == []


def test_merging_is_only_a_way_of_showing_them_and_leaves_the_handoffs_as_they_are(scene: Team) -> None:
    lin = scene.twins["lin"]
    three_ask(scene)
    scene.ask(ASKERS["xu"], lin, REPORT)
    before = [(h.id, h.status, h.asker, h.conversation_id, h.question) for h in scene.team.handoffs()]
    assert len(before) == 4

    page = scene.page(lin)
    ids = [h["id"] for h in page["waiting"]]
    [group] = page["groups"]
    # Three of the four are one matter; each handoff is still its own, none is lost, none is new.
    assert len(group) == 3 and set(group) < set(ids) and len(ids) == 4
    assert {h.asker for h in scene.team.handoffs() if h.id in group} == set(ASKERS.values())
    assert [(h.id, h.status, h.asker, h.conversation_id, h.question) for h in scene.team.handoffs()] == before
    assert page["pending"] == 4
    # The twin's reading of each, for the card: it had nothing to say.
    assert {h["twin_mode"] for h in page["waiting"] if h["id"] in group} == {"abstain"}


def test_one_reply_goes_to_each_askers_own_conversation_and_keeps_each_handoff_its_own(scene: Team) -> None:
    lin = scene.twins["lin"]
    conversations = three_ask(scene)
    scene.ask(ASKERS["xu"], lin, REPORT)
    group = scene.page(lin)["groups"][0]
    before = handoff_count(scene)

    scene.as_(LIN)
    sent = scene.web.post("/api/persona/handoffs/reply-many", json={"ids": group, "text": ANSWER}, headers=lin.headers)
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert set(body["done"]) == set(group) and body["failed"] == [] and body["team_answer"] is None
    # Nothing was merged in the database: the same number of handoffs, each settled as its own.
    assert handoff_count(scene) == before
    assert {h.status for h in scene.team.handoffs() if h.id in group} == {"replied"}
    assert body["pending"] == 1
    # Each asker has the person's words in their own conversation, as theirs and marked with their own handoff.
    for who, conversation in conversations.items():
        mine = [t for t in scene.turns(ASKERS[who], lin, conversation) if t["role"] == "self"]
        assert [t["content"] for t in mine] == [ANSWER]
        [h] = [h for h in scene.team.handoffs() if h.conversation_id == conversation]
        assert mine[0]["handoff_id"] == h.id
    # It is kept as a memory once for the matter, not once for each asker.
    assert scene.sources(lin) == [f"回答：{TEMPLATE['xu']}"]


def test_a_conversation_deleted_meanwhile_does_not_stop_the_others_and_is_told(scene: Team) -> None:
    lin = scene.twins["lin"]
    conversations = three_ask(scene)
    group = scene.page(lin)["groups"][0]
    scene.as_(ASKERS["chen"])
    assert scene.web.delete(f"/api/conversations/{conversations['chen']}", headers=lin.headers).status_code == 200
    scene.as_(LIN)
    sent = scene.web.post(
        "/api/persona/handoffs/reply-many", json={"ids": group, "text": ANSWER}, headers=lin.headers
    ).json()
    assert len(sent["done"]) == 2 and len(sent["failed"]) == 1
    assert "删掉了" in sent["failed"][0]["detail"]
    # Those who are not the person's to answer, and nothing at all, are refused.
    assert (
        scene.web.post(
            "/api/persona/handoffs/reply-many", json={"ids": ["nope"], "text": ANSWER}, headers=lin.headers
        ).status_code
        == 404
    )


# ------------------------------------------------------------------ making it the team's


def make_team_answer(scene: Team) -> tuple[dict[str, str], dict[str, Any]]:
    """The matter asked three times and answered once, made a team answer in the same step."""
    lin = scene.twins["lin"]
    conversations = three_ask(scene)
    group = scene.page(lin)["groups"][0]
    scene.as_(LIN)
    sent = scene.web.post(
        "/api/persona/handoffs/reply-many",
        json={"ids": group, "text": ANSWER, "team_answer": {"title": "旧版 Word 模板还支持吗？"}},
        headers=lin.headers,
    )
    assert sent.status_code == 200, sent.text
    made = sent.json()["team_answer"]
    assert made is not None
    return conversations, made  # type: ignore[return-value]


def test_a_team_answer_that_did_not_come_out_is_told_apart_from_replies_that_did_not_go_out(
    scene: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    lin = scene.twins["lin"]
    three_ask(scene)
    group = scene.page(lin)["groups"][0]

    def refuse(*_: Any, **__: Any) -> Any:
        raise HandoffRefused("这条已经设为团队答案了")

    monkeypatch.setattr(HandoffDesk, "make_team_answer", refuse)
    scene.as_(LIN)
    sent = scene.web.post(
        "/api/persona/handoffs/reply-many",
        json={"ids": group, "text": ANSWER, "team_answer": {"title": "旧版 Word 模板还支持吗？"}},
        headers=lin.headers,
    )
    assert sent.status_code == 200, sent.text
    body = sent.json()
    # Every reply went out; only the team answer is missing, and that is said on its own.
    assert set(body["done"]) == set(group) and body["failed"] == [] and body["team_answer"] is None
    assert body["team_answer_error"] == "这条已经设为团队答案了"


def test_a_reply_can_be_made_a_team_answer_in_the_same_step_under_the_persons_name(scene: Team) -> None:
    lin = scene.twins["lin"]
    _, made = make_team_answer(scene)
    assert made["title"] == "旧版 Word 模板还支持吗？" and made["body"] == ANSWER
    assert made["status"] == "valid" and made["owner_name"] == "林舟" and made["persona_id"] == lin.persona
    [stored] = scene.team.team_answers()
    assert stored.id == made["id"] and stored.owner == LIN and stored.status == "valid"
    assert stored.handoff_id is not None and stored.source_id is not None
    # The reply is also a memory colleagues may use, and the team answer is found by meaning.
    assert scene.sources(lin) == [f"回答：{TEMPLATE['xu']}"]
    scene.as_(LIN)
    listed = scene.web.get("/api/persona/team-answers", headers=lin.headers).json()["team_answers"]
    assert [a["id"] for a in listed] == [made["id"]]
    # The page says how many the person has set.
    assert scene.page(lin)["answers"] == {"total": 1, "stale": 0}


def test_only_the_person_can_make_revise_or_withdraw_their_team_answer(scene: Team) -> None:
    lin = scene.twins["lin"]
    _, made = make_team_answer(scene)
    [h] = [h for h in scene.team.handoffs() if h.id == scene.team.team_answers()[0].handoff_id]
    # A manager (the administrator) and a colleague cannot, and cannot read them either.
    for who in (ADMIN, ASKERS["xu"], WANG):
        scene.as_(who)
        base = {"headers": lin.headers}
        assert scene.web.get("/api/persona/team-answers", **base).status_code == 403
        assert scene.web.post("/api/persona/team-answers", json={"handoff_id": h.id}, **base).status_code == 403
        assert (
            scene.web.patch(
                f"/api/persona/team-answers/{made['id']}", json={"title": "x", "body": "y"}, **base
            ).status_code
            == 403
        )
        assert scene.web.post(f"/api/persona/team-answers/{made['id']}/withdraw", **base).status_code == 403
        assert (
            scene.web.post("/api/persona/handoffs/reply-many", json={"ids": [h.id], "text": "好"}, **base).status_code
            == 403
        )
    assert scene.team.team_answers()[0].status == "valid"
    # Nor can the same reply be made a second team answer.
    scene.as_(LIN)
    again = scene.web.post("/api/persona/team-answers", json={"handoff_id": h.id}, headers=lin.headers)
    assert again.status_code == 409 and "已经设为团队答案" in again.json()["detail"]
    # A reply that has not been sent cannot be one.
    scene.ask(ASKERS["xu"], lin, REPORT)
    [waiting] = [h for h in scene.team.handoffs(statuses=("delivered",))]
    scene.as_(LIN)
    refused = scene.web.post("/api/persona/team-answers", json={"handoff_id": waiting.id}, headers=lin.headers)
    assert refused.status_code == 409 and "先回复" in refused.json()["detail"]


def test_the_person_can_make_a_reply_a_team_answer_later_with_a_title_of_their_own(scene: Team) -> None:
    lin = scene.twins["lin"]
    scene.ask(ASKERS["xu"], lin, TEMPLATE["xu"])
    [h] = scene.team.handoffs()
    scene.as_(LIN)
    assert (
        scene.web.post(
            f"/api/persona/handoffs/{h.id}/reply", json={"text": ANSWER, "remember": False}, headers=lin.headers
        ).status_code
        == 200
    )
    assert scene.sources(lin) == []
    made = scene.web.post(
        "/api/persona/team-answers", json={"handoff_id": h.id, "title": "旧模板还能导出吗"}, headers=lin.headers
    )
    assert made.status_code == 201, made.text
    assert made.json()["team_answer"]["title"] == "旧模板还能导出吗" and made.json()["team_answer"]["body"] == ANSWER
    # It was kept as a memory then, as every team answer is.
    assert scene.sources(lin) == [f"回答：{TEMPLATE['xu']}"]
    too_long = scene.web.post(
        "/api/persona/team-answers", json={"handoff_id": h.id, "title": "x" * 300}, headers=lin.headers
    )
    assert too_long.status_code == 400


# ------------------------------------------------------------------ quoted by every twin


def test_a_colleague_who_asks_any_twin_gets_the_answer_as_a_card_that_does_not_say_who_asked_before(
    scene: Team,
) -> None:
    wang = scene.twins["wang"]
    make_team_answer(scene)
    scene.llm.plan["模板"] = {"reply": "我补一句：迁移找陈一。", "meta": {"owner_part": "decide", "mode": "grounded"}}
    conversation, final = scene.ask(ASKERS["zhou"], wang, "我们客户问旧版 Word 模板导出还能用吗")
    [card] = final["team_answers"]
    assert card["title"] == "旧版 Word 模板还支持吗？" and card["body"] == ANSWER
    assert card["owner_name"] == "林舟" and card["status"] == "valid" and card["confirmed_at"][:4] == "2026"
    # Nothing in it says who asked, and the card was handed to the twin as material it must not repeat.
    assert set(card) == {
        "id",
        "persona_id",
        "owner_name",
        "title",
        "body",
        "confirmed_at",
        "status",
        "stale_note",
        "partial",
    }
    assert "【团队答案】" in scene.llm.seen[-1] and ANSWER in scene.llm.seen[-1]
    assert "## 团队答案" in scene.llm.systems[-1]
    # The twin's own words stand apart from the card; the question is the team's now, so nothing is handed to 王屿.
    assert final["reply"] == "我补一句：迁移找陈一。" and "handoff" not in final
    assert scene.team.handoffs(persona_id=wang.persona) == []
    # The conversation keeps the card as it was shown.
    twin_turn = next(t for t in scene.turns(ASKERS["zhou"], wang, conversation) if t["role"] == "twin")
    assert [c["id"] for c in twin_turn["reply"]["team_answers"]] == [card["id"]]


def test_a_matter_the_team_has_no_answer_to_is_answered_as_before(scene: Team) -> None:
    wang = scene.twins["wang"]
    make_team_answer(scene)
    _, final = scene.ask(ASKERS["xu"], wang, REPORT)
    assert "team_answers" not in final and "【团队答案】" not in scene.llm.seen[-1]
    assert "## 团队答案" not in scene.llm.systems[-1]


def test_the_question_box_returns_the_team_answers_to_everyone_but_the_person_who_confirmed_them(scene: Team) -> None:
    _, made = make_team_answer(scene)
    question = "旧版 Word 模板导出还支持吗"
    scene.as_(ASKERS["xu"])
    found = scene.web.get("/api/personas/ask", params={"q": question}, headers=CSRF)
    assert found.status_code == 200, found.text
    [card] = found.json()["team_answers"]
    assert card["id"] == made["id"] and card["body"] == ANSWER and card["owner_name"] == "林舟"
    assert "asker" not in card and card["status"] == "valid"
    # The person's own question does not bring their own answer back to them.
    scene.as_(LIN)
    own = scene.web.get("/api/personas/ask", params={"q": question}, headers=CSRF)
    assert own.status_code == 200 and own.json()["team_answers"] == []


def test_the_person_asking_their_own_assistant_is_not_shown_their_own_answer(scene: Team) -> None:
    lin = scene.twins["lin"]
    make_team_answer(scene)
    _, final = scene.ask(LIN, lin, "旧版 Word 模板导出还支持吗")
    assert "team_answers" not in final


def test_still_in_doubt_the_asker_can_ask_the_person_who_confirmed_it_in_their_own_name(scene: Team) -> None:
    lin, wang = scene.twins["lin"], scene.twins["wang"]
    make_team_answer(scene)
    _, final = scene.ask(ASKERS["zhou"], wang, "旧版 Word 模板导出还支持吗")
    [card] = final["team_answers"]
    scene.as_(ASKERS["zhou"])
    asked = scene.web.post(
        f"/api/personas/team-answers/{card['id']}/ask", json={"question": "12 月以后呢？"}, headers=CSRF
    )
    assert asked.status_code == 200, asked.text
    body = asked.json()
    assert body["persona_id"] == lin.persona and body["handoff"]["status"] == "delivered"
    # A new conversation in 林舟's twin, the asker's own, with their question and a handoff to the person.
    turns = scene.turns(ASKERS["zhou"], lin, body["conversation_id"])
    assert [t["role"] for t in turns] == ["user", "twin"] and turns[0]["content"] == "12 月以后呢？"
    [made] = [h for h in scene.team.handoffs(persona_id=lin.persona, statuses=("delivered",))]
    assert made.asker == ASKERS["zhou"] and made.kind == "missing" and "团队答案" in made.ask
    waiting = scene.page(lin)["waiting"]
    assert [w["question"] for w in waiting] == ["12 月以后呢？"]
    # Their reply comes back into that conversation.
    scene.as_(LIN)
    assert (
        scene.web.post(
            f"/api/persona/handoffs/{made.id}/reply", json={"text": "明年也还能转。"}, headers=lin.headers
        ).status_code
        == 200
    )
    assert [t["content"] for t in scene.turns(ASKERS["zhou"], lin, body["conversation_id"]) if t["role"] == "self"] == [
        "明年也还能转。"
    ]
    # Not one's own answer, and not one that is gone.
    scene.as_(LIN)
    assert scene.web.post(f"/api/personas/team-answers/{card['id']}/ask", json={}, headers=CSRF).status_code == 400
    scene.web.post(f"/api/persona/team-answers/{card['id']}/withdraw", headers=lin.headers)
    scene.as_(ASKERS["zhou"])
    assert scene.web.post(f"/api/personas/team-answers/{card['id']}/ask", json={}, headers=CSRF).status_code == 404


def test_asking_the_person_again_while_they_have_not_answered_is_told_where_the_first_went(scene: Team) -> None:
    lin, wang = scene.twins["lin"], scene.twins["wang"]
    make_team_answer(scene)
    _, final = scene.ask(ASKERS["zhou"], wang, "旧版 Word 模板导出还支持吗")
    [card] = final["team_answers"]

    def press() -> dict[str, Any]:
        scene.as_(ASKERS["zhou"])
        pressed = scene.web.post(
            f"/api/personas/team-answers/{card['id']}/ask", json={"question": "12 月以后呢？"}, headers=CSRF
        )
        assert pressed.status_code == 200, pressed.text
        return pressed.json()  # type: ignore[no-any-return]

    first = press()
    before = len(scene.team.handoffs(persona_id=lin.persona))
    conversations = len(scene.team.conversations(persona_id=lin.persona))
    # The page was loaded again and the button is back: the same conversation, nothing new for the person.
    again = press()
    assert again["conversation_id"] == first["conversation_id"] and again["handoff"]["id"] == first["handoff"]["id"]
    assert len(scene.team.handoffs(persona_id=lin.persona)) == before
    assert len(scene.team.conversations(persona_id=lin.persona)) == conversations
    assert [w["question"] for w in scene.page(lin)["waiting"]] == ["12 月以后呢？"]
    # Once the person has answered, a new question is a new handoff.
    [made] = scene.team.handoffs(persona_id=lin.persona, statuses=("delivered",))
    scene.as_(LIN)
    assert (
        scene.web.post(
            f"/api/persona/handoffs/{made.id}/reply", json={"text": "还能。"}, headers=lin.headers
        ).status_code
        == 200
    )
    later = press()
    assert later["conversation_id"] != first["conversation_id"]


def test_a_twin_the_asker_cannot_open_is_not_asked_for_them(scene: Team) -> None:
    lin, wang = scene.twins["lin"], scene.twins["wang"]
    make_team_answer(scene)
    _, final = scene.ask(ASKERS["zhou"], wang, "旧版 Word 模板导出还支持吗")
    [card] = final["team_answers"]
    scene.as_(LIN)
    assert (
        scene.web.post(f"/api/personas/{lin.persona}/approve", json={"public": False}, headers=CSRF).status_code == 200
    )
    handoffs, conversations = len(scene.team.handoffs()), len(scene.team.conversations(persona_id=lin.persona))
    scene.as_(ASKERS["zhou"])
    refused = scene.web.post(f"/api/personas/team-answers/{card['id']}/ask", json={}, headers=CSRF)
    assert refused.status_code == 409 and "直接联系" in refused.json()["detail"]
    # Nothing was opened where the reply could not be read, and nothing was handed to the person.
    assert len(scene.team.handoffs()) == handoffs
    assert len(scene.team.conversations(persona_id=lin.persona)) == conversations
    # Opened again, it is asked as usual.
    scene.as_(LIN)
    scene.web.post(f"/api/personas/{lin.persona}/approve", json={"public": True}, headers=CSRF)
    scene.as_(ASKERS["zhou"])
    assert scene.web.post(f"/api/personas/team-answers/{card['id']}/ask", json={}, headers=CSRF).status_code == 200


# ------------------------------------------------------------------ taken back


def test_a_withdrawn_team_answer_is_no_longer_quoted_but_conversations_that_had_it_stay(scene: Team) -> None:
    lin, wang = scene.twins["lin"], scene.twins["wang"]
    _, made = make_team_answer(scene)
    conversation, quoted = scene.ask(ASKERS["xu"], wang, "旧版 Word 模板导出还支持吗")
    assert [c["id"] for c in quoted["team_answers"]] == [made["id"]]

    scene.as_(LIN)
    gone = scene.web.post(f"/api/persona/team-answers/{made['id']}/withdraw", headers=lin.headers)
    assert gone.status_code == 200 and gone.json()["team_answer"]["status"] == "withdrawn"
    assert scene.web.get("/api/persona/team-answers", headers=lin.headers).json()["team_answers"] == []
    assert scene.page(lin)["answers"] == {"total": 0, "stale": 0}
    # The same matter, asked again, anywhere: not quoted, and the twin is told nothing of it.
    scene.llm.seen.clear()
    for twin in (wang, lin):
        _, again = scene.ask(ASKERS["chen"], twin, "旧版 Word 模板导出还支持吗")
        assert "team_answers" not in again
    assert all("【团队答案】" not in seen for seen in scene.llm.seen)
    # The matching is off for good: no vector is left to match, nor can it be revived or withdrawn twice.
    assert scene.team.answer_vectors() == {}
    answers = TeamAnswers(scene.team, lambda _: "林舟")
    assert answers.match("旧版 Word 模板导出", TopicEmbedder()) == []
    scene.as_(LIN)
    again_gone = scene.web.post(f"/api/persona/team-answers/{made['id']}/withdraw", headers=lin.headers)
    assert again_gone.status_code == 409
    revised = scene.web.patch(
        f"/api/persona/team-answers/{made['id']}", json={"title": "x", "body": "y"}, headers=lin.headers
    )
    assert revised.status_code == 409
    # What it said in the conversation it was in is as it was, though its state there is not changed.
    twin_turn = next(t for t in scene.turns(ASKERS["xu"], wang, conversation) if t["role"] == "twin")
    [shown] = twin_turn["reply"]["team_answers"]
    assert shown["body"] == ANSWER and shown["status"] == "valid"


def test_the_answers_of_a_twin_in_the_trash_are_not_quoted_until_it_is_back(scene: Team) -> None:
    lin, wang = scene.twins["lin"], scene.twins["wang"]
    _, made = make_team_answer(scene)
    scene.as_(ADMIN)
    assert scene.web.delete(f"/api/personas/{lin.persona}", headers=CSRF).status_code == 200
    _, hidden = scene.ask(ASKERS["xu"], wang, "旧版 Word 模板导出还支持吗")
    assert "team_answers" not in hidden
    scene.as_(ADMIN)
    assert scene.web.post(f"/api/personas/{lin.persona}/restore", headers=CSRF).status_code == 200
    _, back = scene.ask(ASKERS["xu"], wang, "旧版 Word 模板导出还支持吗")
    assert [c["id"] for c in back["team_answers"]] == [made["id"]]


def test_a_twin_taken_away_for_good_takes_its_team_answers_with_it(scene: Team) -> None:
    make_team_answer(scene)
    lin = scene.twins["lin"]
    scene.team.forget_persona(lin.persona)
    # Gone for good, words and all: not kept as a withdrawn answer.
    assert scene.team.team_answers() == [] and scene.team.answer_vectors() == {}


# ------------------------------------------------------------------ the person says otherwise later


def stale_check(scene: Team, said: str, *, index: int) -> int:
    """The person writes something down that may not agree; the check that runs after a build looks at it."""
    lin = scene.twins["lin"]
    settings = Settings(db_path=lin.path)
    scene.llm.verdicts["Contradiction"] = {"index": index, "reason": "对不上"}
    with PersonaStore(lin.path) as store:
        store.put_source(parse_note(said, settings, "周会记录"))
        index_persona(store, scene.embedder, settings)
        answers = TeamAnswers(scene.team, lambda _: "林舟")
        return answers.check_stale(lin.persona, store, scene.llm, scene.embedder, settings, "林舟")


def test_what_the_person_says_later_that_does_not_agree_makes_the_answer_possibly_out_of_date(scene: Team) -> None:
    lin, wang = scene.twins["lin"], scene.twins["wang"]
    _, made = make_team_answer(scene)
    earlier, quoted = scene.ask(ASKERS["chen"], wang, "旧版 Word 模板导出还支持吗")
    assert quoted["team_answers"][0]["status"] == "valid"

    assert stale_check(scene, "旧版 Word 模板其实 10 月底就停了，导出只剩新模板。", index=1) == 1
    [answer] = scene.team.team_answers()
    assert answer.status == "stale" and "周会记录" in answer.stale_note and "10 月底" in answer.stale_note
    # The model was shown the answer and what was said since, and the card says so where it is quoted.
    name, _system, user = scene.llm.structured_calls[-1]
    assert name == "Contradiction" and ANSWER in user and "10 月底" in user
    _, final = scene.ask(ASKERS["xu"], wang, "旧版 Word 模板导出还支持吗")
    [card] = final["team_answers"]
    assert card["status"] == "stale" and "10 月底" in card["stale_note"]
    assert "可能已经变了" in prompt_line(card)
    # A conversation that already had the card shows it in doubt from then on.
    card_turn = next(t for t in scene.turns(ASKERS["chen"], wang, earlier) if t["role"] == "twin")
    [shown] = card_turn["reply"]["team_answers"]
    assert shown["status"] == "stale" and "10 月底" in shown["stale_note"]

    # It is not judged again unless more is said; the person's two ways out: it stands, or they correct it.
    calls = len(scene.llm.structured_calls)
    scene.as_(LIN)
    kept = scene.web.post(f"/api/persona/team-answers/{made['id']}/keep", headers=lin.headers)
    assert kept.status_code == 200 and kept.json()["team_answer"]["status"] == "valid"
    back = next(t for t in scene.turns(ASKERS["chen"], wang, earlier) if t["role"] == "twin")
    assert (
        back["reply"]["team_answers"][0]["status"] == "valid" and back["reply"]["team_answers"][0]["stale_note"] == ""
    )
    scene.as_(LIN)
    assert stale_check(scene, "旧版 Word 模板其实 10 月底就停了，导出只剩新模板。", index=1) == 0
    assert len(scene.llm.structured_calls) == calls and scene.team.team_answers()[0].status == "valid"

    revised = scene.web.patch(
        f"/api/persona/team-answers/{made['id']}",
        json={"title": "旧版 Word 模板还支持吗？", "body": "旧版 Word 模板支持到 10 月 31 日。"},
        headers=lin.headers,
    )
    assert revised.status_code == 200 and revised.json()["team_answer"]["body"].endswith("10 月 31 日。")
    assert scene.team.team_answers()[0].status == "valid" and scene.team.team_answers()[0].stale_note == ""
    _, quoted = scene.ask(ASKERS["zhou"], wang, "旧版 Word 模板导出还支持吗")
    assert quoted["team_answers"][0]["body"].endswith("10 月 31 日。")


@pytest.mark.parametrize("kept_by", ["note", "item"])
def test_what_the_person_keeps_to_themself_never_makes_an_answer_out_of_date(scene: Team, kept_by: str) -> None:
    """The note that says otherwise is the person's own (a note kept private, or words only an item of their own
    tier stands on): it is not looked at, so it is never quoted to colleagues on the card."""
    make_team_answer(scene)
    lin = scene.twins["lin"]
    settings = Settings(db_path=lin.path)
    scene.llm.verdicts["Contradiction"] = {"index": 1, "reason": "对不上"}
    calls = len(scene.llm.structured_calls)
    with PersonaStore(lin.path) as store:
        parsed = parse_note("旧版 Word 模板其实 10 月底就停了，私下说说。", settings, "私人笔记")
        store.put_source(parsed)
        if kept_by == "note":
            store.set_note_tier(parsed.source.source_id, "self")
        else:
            said = parsed.expressions[0]
            base = item("pi_private", "2.1", "旧模板其实早停了", sources=1)
            private = base.model_copy(
                update={
                    "evidence": [
                        base.evidence[0].model_copy(
                            update={"expression_id": said.expression_id, "source_id": said.source_id}
                        )
                    ]
                }
            )
            store.replace_facet_items("2.1", [*store.list_items("2.1"), private])
            store.set_item_tier("pi_private", "self")
        index_persona(store, scene.embedder, settings)
        answers = TeamAnswers(scene.team, lambda _: "林舟")
        assert answers.check_stale(lin.persona, store, scene.llm, scene.embedder, settings, "林舟") == 0
    [answer] = scene.team.team_answers()
    assert answer.status == "valid" and "10 月底" not in answer.stale_note
    assert not any("10 月底" in user for _, _, user in scene.llm.structured_calls[calls:])


def test_something_that_does_not_contradict_it_leaves_the_answer_standing(scene: Team) -> None:
    make_team_answer(scene)
    assert stale_check(scene, "转换脚本由陈一维护，旧文件一次就能转完，模板的事不用担心。", index=0) == 0
    assert scene.team.team_answers()[0].status == "valid"
    # What was looked at is not looked at again, and nothing new to look at costs no model call.
    calls = len(scene.llm.structured_calls)
    answers = TeamAnswers(scene.team, lambda _: "林舟")
    lin = scene.twins["lin"]
    with PersonaStore(lin.path) as store:
        assert (
            answers.check_stale(lin.persona, store, scene.llm, scene.embedder, Settings(db_path=lin.path), "林舟") == 0
        )
    assert len(scene.llm.structured_calls) == calls


def test_a_model_that_fails_the_check_leaves_the_answer_as_it_was(scene: Team) -> None:
    from twin.llm import LLMError

    make_team_answer(scene)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise LLMError("down")

    scene.llm.handler = fail  # type: ignore[attr-defined]
    lin = scene.twins["lin"]
    settings = Settings(db_path=lin.path)
    with PersonaStore(lin.path) as store:
        store.put_source(parse_note("旧模板 10 月底停。", settings, "周会记录"))
        index_persona(store, scene.embedder, settings)
        answers = TeamAnswers(scene.team, lambda _: "林舟")
        assert answers.check_stale(lin.persona, store, scene.llm, scene.embedder, settings, "林舟") == 0
    assert scene.team.team_answers()[0].status == "valid"


# ------------------------------------------------------------------ replies the twin keeps using


def test_a_reply_the_twin_has_used_twice_is_offered_as_a_team_answer_until_turned_down(scene: Team) -> None:
    lin = scene.twins["lin"]
    scene.ask(ASKERS["xu"], lin, REPORT)
    [h] = scene.team.handoffs()
    scene.as_(LIN)
    assert (
        scene.web.post(
            f"/api/persona/handoffs/{h.id}/reply", json={"text": "按项目写。"}, headers=lin.headers
        ).status_code
        == 200
    )
    assert scene.page(lin)["often"] == []
    # A memory stands on the reply; two colleagues are answered from it afterwards.
    with PersonaStore(lin.path) as store:
        source = next(s for s in store.list_sources())
        memory = item("pi_report", "5.2", "周报按项目写")
        memory.evidence[0].expression_id = f"{source.source_id}#00000"
        memory.evidence[0].source_id = source.source_id
        store.replace_facet_items("5.2", [memory])
        for who in ("chen", "zhou"):
            conversation = store.create_conversation(ASKERS[who])
            scene.team.record_conversation(
                conversation,
                lin.persona,
                ASKERS[who],
                "colleague",
                "周报",
                dt.datetime.now(dt.UTC).isoformat(),
                asker_name=who,
            )
            store.append_conversation_turn(conversation, ASKERS[who], "user", REPORT)
            store.append_conversation_turn(
                conversation,
                ASKERS[who],
                "twin",
                "按项目。",
                {"reply": "按项目。", "mode": "grounded", "citations": ["pi_report"]},
            )
    [row] = scene.page(lin)["often"]
    assert row["handoff_id"] == h.id and row["uses"] == 2 and set(row["askers"]) == {"chen", "zhou"}

    # 不用: not offered again. Making it a team answer takes it off the list too.
    assert scene.web.post(f"/api/persona/handoffs/{h.id}/often/decline", headers=lin.headers).status_code == 200
    assert scene.page(lin)["often"] == []
    scene.team.delete_meta(f"answers:declined:{h.id}")
    assert len(scene.page(lin)["often"]) == 1
    assert (
        scene.web.post("/api/persona/team-answers", json={"handoff_id": h.id}, headers=lin.headers).status_code == 201
    )
    assert scene.page(lin)["often"] == []


def test_the_teams_database_holds_the_new_tables_and_only_by_appended_migrations(tmp_path: Path) -> None:
    import sqlite3

    with TeamDB(tmp_path / "team.db") as db:
        assert db.schema_version() >= 5
    with sqlite3.connect(tmp_path / "team.db") as raw:
        names = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"team_answers", "team_answer_vectors", "facet_coverage", "delegations"} <= names


def test_the_persons_team_answers_list_those_in_doubt_first_and_the_rest_the_newest_first(scene: Team) -> None:
    lin = scene.twins["lin"]
    scene.llm.plan["排期"] = {"reply": "这个得问林舟。", "meta": {"owner_part": "decide", "owner_ask": "排期"}}
    scene.llm.plan[REPORT]["meta"]["mode"] = "abstain"
    _, oldest = make_team_answer(scene)
    made = [oldest]
    for question in (REPORT, "排期延到几号？"):
        scene.ask(ASKERS["xu"], lin, question)
        [waiting] = scene.team.handoffs(persona_id=lin.persona, statuses=("delivered",))
        scene.as_(LIN)
        assert (
            scene.web.post(
                f"/api/persona/handoffs/{waiting.id}/reply", json={"text": "按项目写。"}, headers=lin.headers
            ).status_code
            == 200
        )
        created = scene.web.post("/api/persona/team-answers", json={"handoff_id": waiting.id}, headers=lin.headers)
        assert created.status_code == 201, created.text
        made.append(created.json()["team_answer"])
    # Days apart, so the order does not rest on the clock; the middle one is in doubt.
    with scene.team._tx() as db:
        for days, answer in zip((3, 2, 1), made, strict=True):
            when = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).isoformat()
            db.execute("UPDATE team_answers SET confirmed_at = ? WHERE id = ?", (when, answer["id"]))
        db.execute("UPDATE team_answers SET status = 'stale' WHERE id = ?", (made[1]["id"],))
    scene.as_(LIN)
    listed = scene.web.get("/api/persona/team-answers", headers=lin.headers).json()["team_answers"]
    assert [a["id"] for a in listed] == [made[1]["id"], made[2]["id"], made[0]["id"]]
