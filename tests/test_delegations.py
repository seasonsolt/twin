"""Delegation: the person's assistant asks colleagues' twins in their name.

From 我的分身 the person says 帮我问问王屿和陈一：… and the assistant puts the question to those twins, at most three,
one conversation each, the person's own and answered from what colleagues may use. It asks no further: a twin that was
asked this way asks nobody, which the team database refuses to write otherwise. What a twin cannot settle goes to its
person only when the asker presses 转给本人."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from teamkit import ADMIN, Team, item, make_web

from twin.delegations import Asked, Unclear, mentions, parse, target_state
from twin.persona.store import PersonaStore
from twin.teamdb import DelegationRefused, TeamDB

LIN = "lin@xjjk.com"
QUESTION = "旧模板延到明年 3 月，客户能接受吗？脚本还按 12 月做完吗？"
SAY = f"帮我问问王屿和陈一：{QUESTION}"
SECRET = "SECRET-FAMILY-9a"
PLAN = {
    "王屿|旧模板": {"reply": "能接受。合同写死日期的那家，要问沈从。", "meta": {"mode": "grounded"}},
    "陈一|旧模板": {
        "reply": "脚本做完七成。排期我回头答复你。",
        "meta": {"mode": "general", "owner_part": "decide", "owner_ask": "脚本排期怎么定"},
    },
    "沈从|旧模板": {"reply": "合同那家要延的话，我来跟客户谈。", "meta": {"mode": "grounded"}},
}
KNOWN = {"王屿": ["p1"], "陈一": ["p2"], "沈从": ["p3"], "周宁": ["p4", "p5"]}


# ------------------------------------------------------------------ reading what the person said


def test_the_cue_names_and_question_are_read_from_how_the_person_says_it() -> None:
    assert parse(SAY, KNOWN) == Asked(("王屿", "陈一"), QUESTION)
    assert parse("请帮我问问沈从，旧模板延期行不行", KNOWN) == Asked(("沈从",), "旧模板延期行不行")
    assert parse("替我问一下王屿、陈一、沈从 脚本什么时候好", KNOWN) == Asked(
        ("王屿", "陈一", "沈从"), "脚本什么时候好"
    )
    assert parse("帮我问问王屿的分身：怎么看", KNOWN) == Asked(("王屿",), "怎么看")
    # The same name twice is asked once.
    assert parse("帮我问问王屿和王屿：好吗", KNOWN) == Asked(("王屿",), "好吗")
    # Anything else is an ordinary message to the assistant.
    for message in ("我上周答应过谁什么", "王屿怎么看旧模板？", "问问王屿", "记一下，帮我问问王屿的事"):
        assert parse(message, KNOWN) is None
    # A question for the assistant that happens to start the same way is not an errand to a colleague.
    for message in ("帮我问一下，下周的会几点开？", "帮我问问看我上周答应过谁什么"):
        assert parse(message, KNOWN) is None, message


def test_what_cannot_be_carried_out_is_said_and_nobody_is_asked() -> None:
    too_many = parse("帮我问问王屿、陈一、沈从和周宁：行吗", {**KNOWN, "周宁": ["p4"]})
    assert isinstance(too_many, Unclear) and "最多问 3 位" in too_many.reply
    unknown = parse("帮我问问赵六：行吗", KNOWN)
    assert isinstance(unknown, Unclear) and "「赵六」" in unknown.reply
    ambiguous = parse("帮我问问周宁：行吗", KNOWN)
    assert isinstance(ambiguous, Unclear) and "不止一位叫「周宁」" in ambiguous.reply
    nothing = parse("帮我问问王屿和陈一", KNOWN)
    assert isinstance(nothing, Unclear) and "问王屿、陈一什么" in nothing.reply
    nobody = parse("帮我问问", KNOWN)
    assert isinstance(nobody, Unclear) and "要问谁" in nobody.reply
    own = parse("帮我问问林舟：行吗", KNOWN, own={"林舟"})
    assert isinstance(own, Unclear) and "自己的分身" in own.reply


def test_an_answer_that_sends_the_asker_elsewhere_offers_that_person_in_the_order_they_come() -> None:
    others = {"沈从": "p3", "陈一": "p2", "王屿": "p1"}
    assert mentions("合同写死日期的那家，要问沈从。", others) == [("沈从", "p3")]
    assert mentions("先找陈一要脚本，再问问沈从", others) == [("陈一", "p2"), ("沈从", "p3")]
    # Only a name the answer sends the asker to: saying it is not enough.
    assert mentions("沈从上周说过这事", others) == []


def test_where_a_card_stands_follows_the_reply_the_handoff_and_what_the_person_said() -> None:
    plain = {"mode": "grounded", "owner_part": "none"}
    leaves = {"mode": "general", "owner_part": "decide"}
    assert target_state(plain, None, False, False) == "answered"
    assert target_state(leaves, None, False, False) == "needs_owner"
    assert target_state(leaves, None, True, False) == "skipped"
    assert target_state(leaves, "delivered", False, False) == "handed"
    assert target_state(leaves, "replied", False, False) == "replied"
    assert target_state(leaves, "delivered", False, True) == "replied"
    assert target_state(None, None, False, False) == "answered"


# ------------------------------------------------------------------ the team database holds the line at one hop


@pytest.fixture
def db(tmp_path: Path) -> Iterator[TeamDB]:
    with TeamDB(tmp_path / "team.db") as team:
        team.record_conversation("mine", "p-me", LIN, "self", "我的分身", "2026-10-22T09:00:00+00:00")
        yield team


def delegate(db: TeamDB, conversation: str, persona: str, delegation: str, **change: Any) -> None:
    arguments: dict[str, Any] = {
        "asker": LIN,
        "audience": "colleague",
        "via": "delegate",
        "delegation_id": delegation,
        **change,
    }
    db.record_conversation(
        conversation, persona, arguments["asker"], arguments["audience"], "t", "2026-10-22T09:00:00+00:00",
        via=arguments["via"], delegation_id=arguments["delegation_id"],
    )  # fmt: skip


def test_only_the_persons_own_conversation_with_their_assistant_can_start_a_delegation(db: TeamDB) -> None:
    made = db.create_delegation(initiator=LIN, persona_id="p-me", conversation_id="mine", question="问")
    assert db.get_delegation(made.id) == made and db.delegation_of("mine") == made
    # A colleague's conversation, someone else's, one of another twin's, or one that is not there starts nothing.
    db.record_conversation("theirs", "p-you", "x@xjjk.com", "colleague", "t", "2026-10-22T09:00:00+00:00")
    db.record_conversation("mine-else", "p-me", "x@xjjk.com", "self", "t", "2026-10-22T09:00:00+00:00")
    for conversation, persona, initiator in (
        ("theirs", "p-you", "x@xjjk.com"),
        ("mine-else", "p-me", LIN),
        ("mine", "p-you", LIN),
        ("nowhere", "p-me", LIN),
    ):
        with pytest.raises(DelegationRefused):
            db.create_delegation(initiator=initiator, persona_id=persona, conversation_id=conversation, question="问")


def test_a_conversation_an_assistant_asked_cannot_start_another_delegation_however_it_is_written(db: TeamDB) -> None:
    first = db.create_delegation(initiator=LIN, persona_id="p-me", conversation_id="mine", question="问")
    delegate(db, "asked-1", "p-wang", first.id)
    [asked] = db.conversations(delegation_id=first.id)
    assert (asked.via, asked.audience, asked.asker, asked.delegation_id) == ("delegate", "colleague", LIN, first.id)
    # The conversation it made is the colleague tier and a delegate one: not the person's own with their assistant.
    with pytest.raises(DelegationRefused):
        db.create_delegation(initiator=LIN, persona_id="p-wang", conversation_id="asked-1", question="再问")
    # Not even if it were written as the self tier: that is refused as it is written.
    with pytest.raises(DelegationRefused, match="同事能用"):
        delegate(db, "sneaky", "p-wang", first.id, audience="self")
    assert [c.id for c in db.conversations(delegation_id=first.id)] == ["asked-1"]


def test_a_delegate_conversation_must_belong_to_a_delegation_be_the_persons_and_stay_within_three(db: TeamDB) -> None:
    first = db.create_delegation(initiator=LIN, persona_id="p-me", conversation_id="mine", question="问")
    with pytest.raises(DelegationRefused):  # a delegate conversation without a delegation
        delegate(db, "c0", "p-wang", "nope")
    with pytest.raises(DelegationRefused):
        delegate(db, "c0", "p-wang", None)
    with pytest.raises(DelegationRefused, match="归发起代问的人"):
        delegate(db, "c0", "p-wang", first.id, asker="x@xjjk.com")
    with pytest.raises(DelegationRefused, match="不能代问自己"):
        delegate(db, "c0", "p-me", first.id)
    with pytest.raises(DelegationRefused):  # a direct conversation does not belong to one
        delegate(db, "c0", "p-wang", first.id, via="direct")
    for n in (1, 2, 3):
        delegate(db, f"c{n}", f"p-{n}", first.id)
    with pytest.raises(DelegationRefused, match="最多问 3"):
        delegate(db, "c4", "p-4", first.id)
    # A conversation already written is written again (a new title) without counting twice.
    delegate(db, "c1", "p-1", first.id)
    assert [c.id for c in db.conversations(delegation_id=first.id)] == ["c1", "c2", "c3"]
    assert db.delegation_counts(["mine", "elsewhere"]) == {"mine": 3}


def test_what_a_delegate_conversation_hands_on_is_the_persons_to_start(db: TeamDB) -> None:
    first = db.create_delegation(initiator=LIN, persona_id="p-me", conversation_id="mine", question="问")
    delegate(db, "asked-1", "p-wang", first.id)
    common: dict[str, Any] = {
        "persona_id": "p-wang", "owner": "wang", "conversation_id": "asked-1", "turn": 2, "asker": LIN,
        "asker_name": "lin（助手代问）", "kind": "missing", "question": "问",
    }  # fmt: skip
    # As an ordinary handoff (what a twin's own answer would make) it is refused for a delegate conversation...
    with pytest.raises(DelegationRefused):
        db.create_handoff(**common)
    # ... and a delegate handoff is refused for an ordinary one, and for anyone but the person who asked.
    db.record_conversation("plain", "p-wang", LIN, "colleague", "t", "2026-10-22T09:00:00+00:00")
    with pytest.raises(DelegationRefused):
        db.create_handoff(**{**common, "conversation_id": "plain"}, via="delegate")
    with pytest.raises(DelegationRefused):
        db.create_handoff(**{**common, "asker": "x@xjjk.com"}, via="delegate")
    with pytest.raises(DelegationRefused):
        db.create_handoff(**{**common, "conversation_id": "nowhere"}, via="delegate")
    made = db.create_handoff(**common, via="delegate")
    assert made is not None and made.via == "delegate"


# ------------------------------------------------------------------ the person's assistant asks


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Team]:
    yield from make_web(tmp_path, monkeypatch, PLAN)


@pytest.fixture
def scene(web: Team) -> Team:
    web.add_twin("lin", LIN, "林舟")
    web.add_twin(
        "wang", "wang@xjjk.com", "王屿", items=[item("pi_w", "5.2", "旧模板的事"), item("pi_s", "1.3", SECRET)]
    )
    web.add_twin("chen", "chen@xjjk.com", "陈一")
    web.add_twin("shen", "shen@xjjk.com", "沈从")
    web.add_twin("closed", "closed@xjjk.com", "未开放", public=False)
    web.add_twin("nobody", "nobody@xjjk.com", "未认领", take=False)
    web.llm.verdicts["Summary"] = {"summary": "客户能接受；脚本排期等陈一；合同那家等沈从。"}
    return web


def tell(scene: Team, message: str = SAY, who: str = LIN, to: str = "lin") -> tuple[str, dict[str, Any]]:
    """``who`` says it to ``to``'s twin (the person to their assistant); the conversation's id and the final reply."""
    twin = scene.twins[to]
    conversation = scene.conversation(who, twin)
    return conversation, scene.ask(who, twin, message, conversation=conversation)[1]


def view(scene: Team, delegation: str, who: str = LIN) -> Any:
    scene.as_(who)
    return scene.web.get(f"/api/persona/delegations/{delegation}", headers=scene.twins["lin"].headers)


def test_the_assistant_asks_in_the_persons_name_one_conversation_each_and_says_who_it_asked(scene: Team) -> None:
    lin, wang, chen = scene.twins["lin"], scene.twins["wang"], scene.twins["chen"]
    mine, final = tell(scene)
    assert final["reply"] == "已用你的名义问了王屿、陈一，本人看得到。"
    # The assistant's own note on what came back is kept apart, with the delegation it belongs to.
    assert final["delegation"]["summary"] == "客户能接受；脚本排期等陈一；合同那家等沈从。"
    assert final["delegation"]["asked"] == 2
    [made] = [scene.team.get_delegation(final["delegation"]["id"])]
    assert made is not None and (made.initiator, made.persona_id, made.conversation_id) == (LIN, lin.persona, mine)
    assert made.question == QUESTION
    asked = scene.team.conversations(delegation_id=made.id)
    assert [(c.persona_id, c.via, c.audience, c.asker, c.asker_name) for c in asked] == [
        (wang.persona, "delegate", "colleague", LIN, "lin（助手代问）"),
        (chen.persona, "delegate", "colleague", LIN, "lin（助手代问）"),
    ]
    # Each is a plain conversation of the person's own, readable by them and nobody else.
    for conversation, twin in zip(asked, (wang, chen), strict=True):
        turns = scene.turns(LIN, twin, conversation.id)
        assert [t["role"] for t in turns] == ["user", "twin"] and turns[0]["content"] == QUESTION
        scene.as_("xu@xjjk.com")
        assert scene.web.get(f"/api/conversations/{conversation.id}", headers=twin.headers).status_code == 404
    # The assistant's own conversation says what happened.
    assert [t["role"] for t in scene.turns(LIN, lin, mine)] == ["user", "twin"]
    # They are listed with the person's other conversations, marked as asked by the assistant, and the assistant's
    # own says how many it asked.
    scene.as_(LIN)
    listed = scene.web.get("/api/personas/conversations").json()["conversations"]
    by_id = {c["id"]: c for c in listed}
    assert {by_id[c.id]["via"] for c in asked} == {"delegate"} and by_id[asked[0].id]["persona_id"] == wang.persona
    scene.as_(LIN)
    own = scene.web.get("/api/personas/conversations", params={"mine": "true"}).json()["conversations"]
    # With the assistant's own list: its conversation (saying how many it asked) and, apart, what it asked.
    assert {c["id"]: (c["via"], c["delegated"]) for c in own} == {
        mine: ("direct", 2),
        asked[0].id: ("delegate", 0),
        asked[1].id: ("delegate", 0),
    }
    assert (
        scene.web.get("/api/personas/conversations", params={"mine": "true", "offset": 50}).json()["conversations"]
        == []
    )


def test_the_twins_answer_from_what_colleagues_may_use_as_they_would_if_the_person_had_asked_themself(
    scene: Team,
) -> None:
    wang = scene.twins["wang"]
    scene.llm.systems.clear()
    scene.llm.seen.clear()
    tell(scene)
    shown_to_wang = [s for s, u in zip(scene.llm.systems, scene.llm.seen, strict=True) if "王屿" in s]
    assert shown_to_wang
    for system, seen in zip(scene.llm.systems, scene.llm.seen, strict=True):
        # Not the assistant's second-person prompt, and nothing the person keeps to themself.
        assert "的助手，正在和" not in system and SECRET not in system + seen
        assert QUESTION.split("，")[0] in seen
    # The question went through the same chat as any colleague's: what is left to the person is marked for handing on.
    assert any("## 转交" in system for system in scene.llm.systems)
    with PersonaStore(wang.path) as store:
        assert store.last_turn_seq(scene.team.conversations(persona_id=wang.persona)[0].id, "twin") == 2


def test_nothing_is_handed_to_a_twins_person_until_the_asker_presses_the_card(scene: Team) -> None:
    chen = scene.twins["chen"]
    _, final = tell(scene)
    assert scene.team.handoffs() == []  # chen's twin left the decision to its person, and the asker has not said
    shown = view(scene, final["delegation"]["id"])
    assert shown.status_code == 200, shown.text
    wang_card, chen_card = shown.json()["targets"]
    assert wang_card["state"] == "answered" and wang_card["name"] == "王屿" and "能接受" in wang_card["answer"]
    assert chen_card["state"] == "needs_owner" and chen_card["ask"] == "脚本排期怎么定"
    assert chen_card["handoff"] is None and chen_card["owner_reply"] is None

    scene.as_(LIN)
    forward = scene.web.post(
        f"/api/persona/delegations/{final['delegation']['id']}/forward",
        json={"conversation_id": chen_card["conversation_id"]},
        headers=scene.twins["lin"].headers,
    )
    assert forward.status_code == 200, forward.text
    [made] = scene.team.handoffs()
    # In the person's name, as asked by their assistant, to its person's 你不在时.
    assert (made.persona_id, made.via, made.asker, made.asker_name, made.kind, made.status) == (
        chen.persona, "delegate", LIN, "lin（助手代问）", "missing", "delivered",
    )  # fmt: skip
    assert made.ask == "脚本排期怎么定" and made.question == QUESTION
    waiting = scene.page(chen)["waiting"]
    assert [(w["asker_name"], w["question"]) for w in waiting] == [("lin（助手代问）", QUESTION)]
    assert forward.json()["targets"][1]["state"] == "handed"
    assert forward.json()["targets"][1]["handoff"]["status_label"] == "已送达"
    # Pressing it again makes no second handoff.
    scene.as_(LIN)
    again = scene.web.post(
        f"/api/persona/delegations/{final['delegation']['id']}/forward",
        json={"conversation_id": chen_card["conversation_id"]},
        headers=scene.twins["lin"].headers,
    )
    assert again.status_code == 409 and len(scene.team.handoffs()) == 1

    # The person's reply comes back into that conversation, to the card, as theirs.
    scene.as_("chen@xjjk.com")
    replied = scene.web.post(
        f"/api/persona/handoffs/{made.id}/reply", json={"text": "排期下周三前给你。"}, headers=chen.headers
    )
    assert replied.status_code == 200, replied.text
    card = view(scene, final["delegation"]["id"]).json()["targets"][1]
    assert card["state"] == "replied" and card["owner_reply"] == "排期下周三前给你。"
    assert [t["content"] for t in scene.turns(LIN, chen, chen_card["conversation_id"]) if t["role"] == "self"] == [
        "排期下周三前给你。"
    ]


def test_not_now_leaves_the_question_where_it_is_for_good(scene: Team) -> None:
    _, final = tell(scene)
    delegation = final["delegation"]["id"]
    chen_card = view(scene, delegation).json()["targets"][1]
    scene.as_(LIN)
    skipped = scene.web.post(
        f"/api/persona/delegations/{delegation}/skip",
        json={"conversation_id": chen_card["conversation_id"]},
        headers=scene.twins["lin"].headers,
    )
    assert skipped.status_code == 200 and skipped.json()["targets"][1]["state"] == "skipped"
    assert view(scene, delegation).json()["targets"][1]["state"] == "skipped"
    assert scene.team.handoffs() == []


def test_a_twin_that_names_someone_else_to_ask_offers_them_and_the_person_decides_within_three(scene: Team) -> None:
    _, final = tell(scene)
    delegation = final["delegation"]["id"]
    wang_card = view(scene, delegation).json()["targets"][0]
    assert [a["name"] for a in wang_card["also"]] == ["沈从"]
    shen = scene.twins["shen"]
    scene.as_(LIN)
    headers = scene.twins["lin"].headers
    added = scene.web.post(
        f"/api/persona/delegations/{delegation}/ask", json={"persona_id": shen.persona}, headers=headers
    )
    assert added.status_code == 200, added.text
    targets = added.json()["targets"]
    assert [t["name"] for t in targets] == ["王屿", "陈一", "沈从"] and "我来跟客户谈" in targets[2]["answer"]
    # Asked in the same name, one hop from the person; no more offered to ask, and no fourth.
    [third] = [c for c in scene.team.conversations(delegation_id=delegation) if c.persona_id == shen.persona]
    assert (third.via, third.asker) == ("delegate", LIN) and targets[0]["also"] == []
    for persona in (shen.persona, scene.twins["wang"].persona, scene.twins["lin"].persona, "nope"):
        refused = scene.web.post(
            f"/api/persona/delegations/{delegation}/ask", json={"persona_id": persona}, headers=headers
        )
        assert refused.status_code == 409, refused.text
    closed = scene.web.post(
        f"/api/persona/delegations/{delegation}/ask",
        json={"persona_id": scene.twins["closed"].persona},
        headers=headers,
    )
    assert closed.status_code == 409 and len(scene.team.conversations(delegation_id=delegation)) == 3


def test_a_twin_that_was_asked_this_way_does_not_ask_others_and_nobody_else_can_delegate(scene: Team) -> None:
    lin, wang = scene.twins["lin"], scene.twins["wang"]
    _, final = tell(scene)
    delegation = final["delegation"]["id"]
    [first, _second] = scene.team.conversations(delegation_id=delegation)
    # The person writing the same words in the conversation their assistant made with 王屿's twin: an ordinary question
    # to that twin, nothing more asked.
    conversation, answer = scene.ask(LIN, wang, "帮我问问沈从：旧模板行不行", conversation=first.id)
    assert "delegation" not in answer
    assert len(scene.team.conversations(delegation_id=delegation)) == 2
    # A colleague writing it to the person's twin: an ordinary question to the twin as well.
    _, colleague = tell(scene, "帮我问问陈一：旧模板怎么办", who="xu@xjjk.com")
    assert "delegation" not in colleague and len(scene.team.conversations(persona_id=lin.persona)) >= 1
    # The administrator looking after the twin is a colleague to it too.
    _, manager = tell(scene, "帮我问问陈一：旧模板怎么办", who=ADMIN)
    assert "delegation" not in manager and scene.team.delegation_of(conversation) is None
    assert len([d for d in scene.team.conversations() if d.via == "delegate"]) == 2


def test_asking_more_than_three_or_someone_who_cannot_be_asked_says_so_and_asks_nobody(scene: Team) -> None:
    for message, said in (
        (f"帮我问问王屿、陈一、沈从和未开放：{QUESTION}", "「未开放」"),  # a twin not open to colleagues
        (f"帮我问问林舟：{QUESTION}", "自己的分身"),
        ("帮我问问王屿", "问王屿什么"),
    ):
        _, final = tell(scene, message)
        assert "delegation" not in final and said in final["reply"] and "已用你的名义" not in final["reply"]
    # Nobody was asked, and no delegation was made.
    assert scene.team.conversations(persona_id=scene.twins["wang"].persona) == []
    assert not [c for c in scene.team.conversations() if c.via == "delegate"]
    # Too many: the fourth of those that can be asked.
    scene.add_twin("fourth", "fourth@xjjk.com", "周石言")
    _, many = tell(scene, f"帮我问问王屿、陈一、沈从、周石言：{QUESTION}")
    assert "最多问 3 位" in many["reply"] and "delegation" not in many
    assert not [c for c in scene.team.conversations() if c.via == "delegate"]


def test_a_twin_nobody_has_taken_can_be_asked_but_has_no_one_to_hand_to(scene: Team) -> None:
    _, final = tell(scene, f"帮我问问未认领：{QUESTION}")
    [card] = view(scene, final["delegation"]["id"]).json()["targets"]
    # It answers like any twin, and there is nobody to press 转给本人 for.
    assert card["name"] == "未认领" and card["state"] == "answered" and card["answer"] == "好的。"
    scene.as_(LIN)
    forward = scene.web.post(
        f"/api/persona/delegations/{final['delegation']['id']}/forward",
        json={"conversation_id": card["conversation_id"]},
        headers=scene.twins["lin"].headers,
    )
    assert forward.status_code == 409 and "没能转给未认领本人" in forward.json()["detail"]
    assert scene.team.handoffs() == []


def test_what_the_person_asks_is_theirs_alone_to_read_and_decide(scene: Team) -> None:
    _, final = tell(scene)
    delegation = final["delegation"]["id"]
    chen_card = view(scene, delegation).json()["targets"][1]
    lin = scene.twins["lin"]
    for who in (ADMIN, "xu@xjjk.com", "wang@xjjk.com"):
        scene.as_(who)
        assert scene.web.get(f"/api/persona/delegations/{delegation}", headers=lin.headers).status_code == 403
        forward = scene.web.post(
            f"/api/persona/delegations/{delegation}/forward",
            json={"conversation_id": chen_card["conversation_id"]},
            headers=lin.headers,
        )
        assert forward.status_code == 403
    # Not another twin's: the delegation is looked for under the person's own twin.
    scene.as_(LIN)
    elsewhere = scene.web.get(f"/api/persona/delegations/{delegation}", headers=scene.twins["wang"].headers)
    assert elsewhere.status_code in (403, 404)
    assert scene.web.get("/api/persona/delegations/nope", headers=lin.headers).status_code == 404
    assert scene.team.handoffs() == []


def test_a_team_answer_of_the_twins_person_is_used_as_it_stands_and_that_twin_is_not_asked(scene: Team) -> None:
    wang = scene.twins["wang"]
    # 王屿 has confirmed an answer to this very matter.
    scene.team.create_team_answer(
        persona_id=wang.persona,
        owner="wang@xjjk.com",
        title="旧模板延期，脚本还按 12 月做完吗",
        body="能接受，不过年底前别动。",
    )
    scene.llm.seen.clear()
    _, final = tell(scene)
    wang_card, chen_card = view(scene, final["delegation"]["id"]).json()["targets"]
    assert wang_card["team_answer"]["body"] == "能接受，不过年底前别动。" and wang_card["state"] == "answered"
    assert "团队答案" in wang_card["answer"]
    # Only the other twin was put to the model.
    assert len(scene.llm.seen) == 1 and chen_card["name"] == "陈一"
    assert scene.team.handoffs() == []


def test_a_twin_that_fails_answers_that_it_could_not_and_the_others_are_still_asked(
    scene: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from twin.llm import LLMError

    original = scene.llm.handle

    def handle(system: str, user: str, schema: Any) -> Any:
        if "陈一" in system and schema.__name__ == "ChatDraft":
            raise LLMError("down")
        return original(system, user, schema)

    scene.llm.handler = handle  # type: ignore[attr-defined]
    _, final = tell(scene)
    wang_card, chen_card = view(scene, final["delegation"]["id"]).json()["targets"]
    assert wang_card["state"] == "answered" and "能接受" in wang_card["answer"]
    assert "没能回答" in chen_card["answer"] and chen_card["state"] == "answered"
    assert final["reply"].startswith("已用你的名义问了王屿、陈一")


def test_a_model_that_cannot_be_reached_holds_no_place_in_the_chat_queue(
    scene: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from twin.web import jobs
    from twin.web.backends import Backends, BackendUnavailable

    def down(self: Backends) -> Any:
        raise BackendUnavailable("down")

    monkeypatch.setattr(jobs, "MAX_PENDING_ANSWERS", 1)
    with monkeypatch.context() as m:
        m.setattr(Backends, "chat_llm", down)
        lin = scene.twins["lin"]
        conversation = scene.conversation(LIN, lin)
        body = {"messages": [{"role": "user", "content": SAY}], "conversation_id": conversation}
        # Twice: a place left held by the first would turn the second away as a full queue (429).
        for _ in range(2):
            response = scene.web.post("/api/persona/chat/stream", json=body, headers=lin.headers)
            assert response.status_code == 503, response.text
    assert tell(scene)[1]["reply"] == "已用你的名义问了王屿、陈一，本人看得到。"


def test_asking_one_more_twin_holds_a_place_in_the_chat_queue_like_the_first_asking(
    scene: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from twin.web import jobs

    _, final = tell(scene)
    delegation = final["delegation"]["id"]
    scene.as_(LIN)
    headers = scene.twins["lin"].headers
    ask = f"/api/persona/delegations/{delegation}/ask"
    held: list[int] = []
    original = jobs.JobManager.admit_stream

    def watching(self: jobs.JobManager) -> Any:
        ticket = original(self)
        held.append(self._streams[0])
        return ticket

    # One place in all: the twin is asked while it is held, and it is given back for the next asking.
    monkeypatch.setattr(jobs, "MAX_PENDING_ANSWERS", 1)
    monkeypatch.setattr(jobs.JobManager, "admit_stream", watching)
    added = scene.web.post(ask, json={"persona_id": scene.twins["shen"].persona}, headers=headers)
    assert added.status_code == 200, added.text
    assert held == [1]

    # A full queue turns it away before anyone is asked.
    def full(self: jobs.JobManager) -> Any:
        raise jobs.TooManyJobs("聊天排队太多，请稍后再试")

    monkeypatch.setattr(jobs.JobManager, "admit_stream", full)
    before = len(scene.team.conversations(delegation_id=delegation))
    turned_away = scene.web.post(ask, json={"persona_id": scene.twins["chen"].persona}, headers=headers)
    assert turned_away.status_code == 429, turned_away.text
    assert len(scene.team.conversations(delegation_id=delegation)) == before
