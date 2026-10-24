"""Lenses: a person lends their judgement to colleagues, facet by facet.

Only a facet that is well founded can be opened (a good deal known, three occasions, mostly the person's own words,
more than one kind of source, no contradiction, and nothing of what they keep to themself); a lens held or taken back
is not used from that moment; its uses keep the question and what it said and no one who asked."""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from teamkit import ADMIN, CSRF, Team, item, make_web

from twin.lenses import LENS_FACETS, STOP_AFTER, LensAudience, judge
from twin.persona.dimensions import FACETS
from twin.persona.gate import MEETING_RECORD, MODE
from twin.persona.items import PersonaItem
from twin.persona.schema import SourceKind
from twin.persona.store import PersonaStore

WANG = "wang@xjjk.com"
SHEN = "shen@xjjk.com"
CHEN = "chen@xjjk.com"
TRADE = "客户嫌报价高时先问清预算是谁定的，让价换条件而不是单方面降"
BASIS = "先问事实再下结论，追问到数字为止"
PRINCIPLE = "答应的事一定做到，做不到提前说"
PRICE_QUESTION = "客户嫌报价高，预算是谁定的？"
OTHER_KINDS = (SourceKind.CHAT, SourceKind.AUDIO)


def ready(item_id: str, facet: str, statement: str, **options: Any) -> PersonaItem:
    """An item that stands well enough to be lent: three occasions, the person's own words, behaviour as well, and two
    kinds of source."""
    return item(item_id, facet, statement, sources=3, behavior=True, kinds=OTHER_KINDS, **options)


def reasons(items: list[PersonaItem], tiers: dict[str, str] | None = None) -> dict[str, tuple[str, ...]]:
    return {v.facet_id: v.reasons for v in judge(items, tiers or {}, dt.date(2026, 10, 1))}


# ------------------------------------------------------------------ which facets can be opened


def test_a_facet_is_opened_when_the_twin_knows_it_well_and_nothing_contradicts() -> None:
    found = reasons(
        [
            ready("a", "3.4", TRADE),
            # Contradicted.
            ready("e", "2.1", "先交付再谈价值", conflict="说的和做的不一样"),
        ]
    )
    assert found["3.4"] == ()
    assert "内容有矛盾" in found["2.1"]
    # A facet the twin hardly knows is not a good deal known, either.
    assert reasons([item("f", "4.1", "先画流程图", sources=1)])["4.1"] == ("了解还不够多",)
    # A facet nothing is known of cannot be opened either.
    assert found["4.2"] == ("还没有记忆",)


def test_occasions_own_words_and_kinds_of_source_count_once_through_the_level() -> None:
    # Fewer occasions, others' words, one kind of source: each weighs on the level and is never a reason of its own.
    thin = [
        item("b", "3.3", BASIS, sources=2, behavior=True, kinds=OTHER_KINDS),
        ready("c", "5.1", "拿手的是大客户谈判", own_words=False),
        item("d", "3.1", "宁可慢一点也不冒险", sources=3, behavior=True),
    ]
    for verdict in judge(thin, {}, dt.date(2026, 10, 1)):
        if verdict.facet_id in ("3.3", "5.1", "3.1"):
            assert verdict.reasons == (() if verdict.level >= 3 else ("了解还不够多",))


def test_only_judgement_is_offered_never_experience_speech_or_life() -> None:
    offered = {v.facet_id for v in judge([], {}, dt.date(2026, 10, 1))}
    assert offered == set(LENS_FACETS)
    names = {f.facet_id: f.dimension_id for f in FACETS}
    assert {names[f] for f in offered} == {"D2", "D3", "D4", "D5"}
    # What a person values, how they decide, think and what they are good at; not 6.x speech, 9.x life.
    assert not {"1.1", "6.1", "7.4", "8.1", "9.3"} & offered


def test_what_the_person_keeps_to_themself_cannot_be_lent_whatever_it_stands_on() -> None:
    items = [ready("a", "3.4", TRADE), ready("b", "2.3", PRINCIPLE)]
    found = reasons(items, {"a": "self"})
    assert found["3.4"] == ("只有本人能用",)
    assert found["2.3"] == ()
    # Opening a facet whose default is theirs alone makes it lendable only item by item.
    private = ready("c", "5.3", "不懂合规细节，找法务")
    assert judge([private], {}, dt.date(2026, 10, 1))[-1].ok  # 5.3 is a colleague-tier facet by default


def test_an_audience_that_cannot_be_read_admits_nobody() -> None:
    assert LensAudience.decode("not json").admits({"p1"}) is False
    assert LensAudience.decode(LensAudience().encode()).admits(set())
    named = LensAudience("people", ("p1",))
    assert LensAudience.decode(named.encode()) == named
    assert named.admits({"p1", "p2"}) and not named.admits({"p2"}) and not named.admits(set())


# ------------------------------------------------------------------ the team


@pytest.fixture
def team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Team]:
    yield from make_web(tmp_path, monkeypatch)


@pytest.fixture
def scene(team: Team) -> Team:
    team.add_twin(
        "wang",
        WANG,
        "王屿",
        items=[
            ready("pi_trade", "3.4", TRADE),
            ready("pi_basis", "3.3", BASIS),
            ready("pi_principle", "2.3", PRINCIPLE),
            # Not well founded yet: said once.
            item("pi_new", "4.2", "遇到新事先拆成三件小事", sources=1),
            # The person's own.
            ready("pi_family", "9.3", "周末陪家人，不接工作电话"),
        ],
    )
    team.add_twin("shen", SHEN, "沈从")
    team.add_twin("chen", CHEN, "陈一")
    return team


def lenses_of(scene: Team, who: str = WANG) -> dict[str, Any]:
    scene.as_(who)
    response = scene.web.get("/api/persona/lenses", headers=scene.twins["wang"].headers)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def publish(
    scene: Team,
    facets: list[str],
    name: str = "大客户谈判",
    audience: dict[str, Any] | None = None,
    who: str = WANG,
) -> Any:
    scene.as_(who)
    return scene.web.post(
        "/api/persona/lenses",
        json={"name": name, "facets": facets, "audience": audience or {"scope": "team"}},
        headers=scene.twins["wang"].headers,
    )


def made(scene: Team, facets: list[str] | None = None, **options: Any) -> str:
    response = publish(scene, facets or ["3.4", "2.3"], **options)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def ask_lens(
    scene: Team, who: str, lens_id: str, question: str = PRICE_QUESTION, conversation: str | None = None
) -> Any:
    wang = scene.twins["wang"]
    scene.as_(who)
    cid = conversation or scene.conversation(who, wang)
    return scene.web.post(
        f"/api/persona/lenses/{lens_id}/ask", json={"question": question, "conversation_id": cid}, headers=wang.headers
    )


def test_the_page_lists_every_facet_with_whether_it_can_be_opened_and_why_not(scene: Team) -> None:
    page = lenses_of(scene)
    by_facet = {f["facet_id"]: f for f in page["facets"]}
    assert page["lenses"] == [] and page["stop_after"] == STOP_AFTER
    assert [f["facet_id"] for f in page["facets"]] == list(LENS_FACETS)
    assert (
        by_facet["3.4"]["ok"]
        and by_facet["3.4"]["label"] == "了解较多"
        and by_facet["3.4"]["dimension"] == "怎么做决定"
    )
    assert not by_facet["4.2"]["ok"] and by_facet["4.2"]["reasons"] == ["了解还不够多"]
    # Life is not a facet a lens can open at all.
    assert "9.3" not in by_facet


def test_a_facet_that_does_not_pass_cannot_be_opened_and_the_refusal_names_it(scene: Team) -> None:
    # How they think: no facet of it passes, so the aspect cannot be opened, and the refusal names the aspect.
    refused = publish(scene, ["3.4", "4.1", "4.2", "4.3", "4.4"])
    assert refused.status_code == 400
    assert "怎么思考" in refused.json()["detail"] and "了解还不够多" in refused.json()["detail"]
    assert "怎么做决定" not in refused.json()["detail"]
    # A facet outside judgement, and nothing at all.
    assert publish(scene, ["9.3"]).status_code == 400
    assert publish(scene, []).status_code == 400
    assert publish(scene, ["3.4"], name="  ").status_code in (400, 422)
    assert lenses_of(scene)["lenses"] == []
    # What the person keeps to themself is not lent even if the facet passed before.
    scene.as_(WANG)
    assert (
        scene.web.put(
            "/api/persona/items/pi_trade/tier", json={"tier": "self"}, headers=scene.twins["wang"].headers
        ).status_code
        == 200
    )
    assert publish(scene, ["3.4"]).status_code == 400
    assert publish(scene, ["2.3"]).status_code == 201


def test_only_the_person_publishes_and_manages_a_lens(scene: Team) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    for who in (ADMIN, SHEN):
        assert publish(scene, ["2.3"], who=who).status_code == 403
        scene.as_(who)
        for method, path in (
            ("get", "/api/persona/lenses"),
            ("post", f"/api/persona/lenses/{lens_id}/pause"),
            ("post", f"/api/persona/lenses/{lens_id}/withdraw"),
            ("get", f"/api/persona/lenses/{lens_id}/uses"),
            ("patch", f"/api/persona/lenses/{lens_id}"),
        ):
            sent = getattr(scene.web, method)(path, headers=wang.headers, **({"json": {}} if method == "patch" else {}))
            assert sent.status_code == 403, (who, path, sent.text)
    assert scene.team.get_lens(lens_id).status == "active"  # type: ignore[union-attr]


def test_a_published_lens_is_seen_with_what_it_opens_and_who_it_is_for(scene: Team) -> None:
    lens_id = made(scene, ["2.3", "3.4"], audience={"scope": "people", "twins": [scene.twins["shen"].persona]})
    [lens] = lenses_of(scene)["lenses"]
    assert lens["id"] == lens_id and lens["name"] == "大客户谈判" and lens["status"] == "active"
    assert [f["name"] for f in lens["facets"]] == ["做事的原则", "常见取舍"]
    assert lens["speaking"] == ["2.3", "3.4"] and lens["stopped"] == [] and lens["uses_week"] == 0
    assert lens["audience"] == {"scope": "people", "twins": [scene.twins["shen"].persona]}


def test_an_aspect_opens_with_the_facets_that_pass_and_the_others_wait(scene: Team) -> None:
    decide = [f for f in LENS_FACETS if f.startswith("3.")]
    response = publish(scene, decide)
    assert response.status_code == 201, response.text
    lens = response.json()
    # The whole aspect is opened; it speaks only from what is well founded, the rest join as the twin learns them.
    assert [f["facet_id"] for f in lens["facets"]] == decide
    assert {f["dimension_id"] for f in lens["facets"]} == {"D3"}
    assert lens["speaking"] == ["3.3", "3.4"]


def test_a_preview_reads_like_the_lens_and_keeps_nothing(scene: Team) -> None:
    scene.as_(WANG)
    wang = scene.twins["wang"]
    shown = scene.web.post("/api/persona/lenses/preview", json={"facets": ["3.4", "4.2"]}, headers=wang.headers)
    assert shown.status_code == 200
    body = shown.json()
    # The facet that does not pass is not previewed; the other is, with the words it stands on.
    assert [v["facet_id"] for v in body["views"]] == ["3.4"]
    assert body["views"][0]["text"] == TRADE and body["views"][0]["basis"][0]["quote"].startswith("原话")
    assert body["settled_by_person"] is True
    assert lenses_of(scene)["lenses"] == []
    assert scene.team.lenses() == []


# ------------------------------------------------------------------ colleagues use it


def test_a_colleague_asks_a_lens_and_gets_what_the_opened_facets_hold_with_their_basis(scene: Team) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    scene.as_(SHEN)
    seen = scene.web.get("/api/persona/lenses/available", headers=wang.headers).json()["lenses"]
    assert [(lens["id"], lens["name"], lens["owner_name"]) for lens in seen] == [(lens_id, "大客户谈判", "王屿")]
    assert [f["name"] for f in seen[0]["facets"]] == ["做事的原则", "常见取舍"]

    cid = scene.conversation(SHEN, wang)
    said = ask_lens(scene, SHEN, lens_id, conversation=cid)
    assert said.status_code == 200, said.text
    body = said.json()
    card = body["lens"]
    assert [v["text"] for v in card["views"]] == [TRADE]
    assert card["views"][0]["facet"] == "常见取舍" and card["views"][0]["basis"][0]["kind"] in ("聊天记录", "音频")
    assert card["owner_name"] == "王屿" and card["note"] == "根据王屿说过的话推测，不代表王屿的意见"
    # A matter of price is the person's to settle, whatever else is said.
    assert card["settled_by_person"] is True and "未开放，可直接问王屿" in body["reply"]
    # It sits in the colleague's own conversation, and hands nothing to the person on its own.
    turns = scene.turns(SHEN, wang, cid)
    assert [t["role"] for t in turns] == ["user", "twin"] and turns[1]["reply"]["lens"]["id"] == lens_id
    assert scene.team.handoffs() == []


def test_a_lens_speaks_only_from_the_facets_that_are_open(scene: Team) -> None:
    lens_id = made(scene, ["2.3"])  # 做事的原则 only
    body = ask_lens(scene, SHEN, lens_id).json()
    # The question is about the trade-off facet, which this lens does not open: it has nothing to say, and says whose
    # it is.
    assert body["lens"]["views"] == [] and body["lens"]["empty"] is True
    assert "没有能回答的内容" in body["reply"] and "直接问王屿" in body["reply"]
    # What it does open is used.
    said = ask_lens(scene, SHEN, lens_id, "答应客户的事做不到怎么办，要提前说吗？").json()
    assert [v["facet_id"] for v in said["lens"]["views"]] == ["2.3"]
    # What the person keeps to themself is never in an answer, though a question may be about it.
    life = ask_lens(scene, SHEN, lens_id, "周末陪家人不接工作电话吗？").json()
    assert life["lens"]["views"] == [] and "陪家人" not in life["reply"]


def test_a_lens_can_be_meant_for_a_colleague_whose_twin_is_private(scene: Team) -> None:
    quiet = scene.add_twin("zhou", "zhou@xjjk.com", "周一", public=False)
    listed = lenses_of(scene)["colleagues"]
    # Every twin a colleague has taken, private ones too, and not the person's own; no account is shown.
    assert {c["id"]: c["name"] for c in listed} == {
        scene.twins["shen"].persona: "沈从",
        scene.twins["chen"].persona: "陈一",
        quiet.persona: "周一",
    }
    assert all(set(c) == {"id", "name"} for c in listed)
    named = made(scene, audience={"scope": "people", "twins": [quiet.persona]})
    assert ask_lens(scene, SHEN, named).status_code == 404


def test_a_lens_can_be_asked_by_everyone_or_only_by_the_people_it_names(scene: Team) -> None:
    named = made(scene, audience={"scope": "people", "twins": [scene.twins["shen"].persona]})
    assert ask_lens(scene, SHEN, named).status_code == 200
    refused = ask_lens(scene, CHEN, named)
    assert refused.status_code == 404
    scene.as_(CHEN)
    assert scene.web.get("/api/persona/lenses/available", headers=scene.twins["wang"].headers).json() == {"lenses": []}
    # Change it to everyone, and 陈一 can.
    scene.as_(WANG)
    adjusted = scene.web.patch(
        f"/api/persona/lenses/{named}", json={"audience": {"scope": "team"}}, headers=scene.twins["wang"].headers
    )
    assert adjusted.status_code == 200 and adjusted.json()["audience"] == {"scope": "team", "twins": []}
    assert ask_lens(scene, CHEN, named).status_code == 200


def test_the_person_does_not_ask_their_own_lens_and_a_visitor_with_no_conversation_of_their_own_is_refused(
    scene: Team,
) -> None:
    lens_id = made(scene)
    assert ask_lens(scene, WANG, lens_id).status_code == 403
    scene.as_(WANG)
    assert scene.web.get("/api/persona/lenses/available", headers=scene.twins["wang"].headers).json() == {"lenses": []}
    # Someone else's conversation is not written into.
    wang = scene.twins["wang"]
    theirs = scene.conversation(CHEN, wang)
    assert ask_lens(scene, SHEN, lens_id, conversation=theirs).status_code == 404
    assert [t["role"] for t in scene.turns(CHEN, wang, theirs)] == []


# ------------------------------------------------------------------ held, taken back, no longer passing


def test_a_held_lens_is_not_used_until_it_is_resumed(scene: Team) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    assert ask_lens(scene, SHEN, lens_id).status_code == 200
    scene.as_(WANG)
    held = scene.web.post(f"/api/persona/lenses/{lens_id}/pause", headers=wang.headers)
    assert held.status_code == 200 and held.json()["status"] == "paused"
    uses = len(scene.team.lens_uses(lens_id))
    assert ask_lens(scene, SHEN, lens_id).status_code == 404
    scene.as_(SHEN)
    assert scene.web.get("/api/persona/lenses/available", headers=wang.headers).json() == {"lenses": []}
    assert len(scene.team.lens_uses(lens_id)) == uses
    # The person still sees it, and can put it back.
    assert [lens["status"] for lens in lenses_of(scene)["lenses"]] == ["paused"]
    scene.as_(WANG)
    assert scene.web.post(f"/api/persona/lenses/{lens_id}/resume", headers=wang.headers).json()["status"] == "active"
    assert ask_lens(scene, SHEN, lens_id).status_code == 200


def test_a_withdrawn_lens_is_not_used_again_and_cannot_be_brought_back(scene: Team) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    assert ask_lens(scene, SHEN, lens_id).status_code == 200
    scene.as_(WANG)
    assert (
        scene.web.post(f"/api/persona/lenses/{lens_id}/withdraw", headers=wang.headers).json()["status"] == "withdrawn"
    )
    uses = len(scene.team.lens_uses(lens_id))
    assert ask_lens(scene, SHEN, lens_id).status_code == 404
    assert len(scene.team.lens_uses(lens_id)) == uses
    for action in ("resume", "pause", "withdraw"):
        scene.as_(WANG)
        assert scene.web.post(f"/api/persona/lenses/{lens_id}/{action}", headers=wang.headers).status_code == 409
    scene.as_(WANG)
    assert (
        scene.web.patch(f"/api/persona/lenses/{lens_id}", json={"name": "新名字"}, headers=wang.headers).status_code
        == 409
    )
    # It is gone from the person's list; a new one can be published in its place.
    assert lenses_of(scene)["lenses"] == []
    assert publish(scene, ["3.4"]).status_code == 201


def test_a_use_is_refused_when_the_lens_is_held_between_looking_and_answering(scene: Team) -> None:
    lens_id = made(scene)
    scene.team.set_lens_status(lens_id, "paused")
    from twin.teamdb import LensUnavailable

    with pytest.raises(LensUnavailable):
        scene.team.record_lens_use(lens_id, "问题", "回答", ["3.4"])
    assert scene.team.lens_uses(lens_id) == []


def test_a_facet_that_stops_passing_stops_being_used(scene: Team) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    assert ask_lens(scene, SHEN, lens_id).json()["lens"]["views"]
    # A contradiction comes into the memory of the trade-off facet.
    with PersonaStore(wang.path) as store:
        store.replace_facet_items("3.4", [ready("pi_trade", "3.4", TRADE, conflict="说的和做的不一样")])
    body = ask_lens(scene, SHEN, lens_id).json()
    assert body["lens"]["views"] == []
    [lens] = lenses_of(scene)["lenses"]
    assert lens["speaking"] == ["2.3"] and lens["failing"] == ["3.4"]
    # And what the person then keeps to themself is not lent either, the other facet included.
    scene.as_(WANG)
    scene.web.put("/api/persona/items/pi_principle/tier", json={"tier": "self"}, headers=wang.headers)
    assert lenses_of(scene)["lenses"][0]["speaking"] == []
    # A lens that speaks from nothing is not offered to colleagues: it could only say it has nothing.
    scene.as_(SHEN)
    assert scene.web.get("/api/persona/lenses/available", headers=wang.headers).json() == {"lenses": []}


def test_a_twin_that_answers_as_a_meeting_record_is_judged_like_any_other(scene: Team) -> None:
    wang = scene.twins["wang"]
    with PersonaStore(wang.path) as store:
        store.set_meta(MODE, MEETING_RECORD)
    lens_id = made(scene)
    assert ask_lens(scene, SHEN, lens_id).json()["lens"]["views"][0]["text"] == TRADE


# ------------------------------------------------------------------ what it was used for


def test_the_uses_keep_the_question_and_what_was_said_and_no_one_who_asked(scene: Team, tmp_path: Path) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    cid_shen = scene.conversation(SHEN, wang)
    assert ask_lens(scene, SHEN, lens_id, conversation=cid_shen).status_code == 200
    assert ask_lens(scene, CHEN, lens_id, "答应客户的事做不到怎么办？").status_code == 200

    scene.as_(WANG)
    shown = scene.web.get(f"/api/persona/lenses/{lens_id}/uses", headers=wang.headers).json()["uses"]
    assert len(shown) == 2
    assert {u["question"] for u in shown} == {PRICE_QUESTION, "答应客户的事做不到怎么办？"}
    assert all(set(u) == {"id", "question", "said", "facets", "corrected", "at"} for u in shown)
    assert any(TRADE in u["said"] for u in shown)
    assert [f["name"] for f in next(u for u in shown if TRADE in u["said"])["facets"]] == ["常见取舍"]
    assert lenses_of(scene)["lenses"][0]["uses_week"] == 2

    # The table has no column for who asked, for the conversation or for a handoff.
    with sqlite3.connect(scene.team.path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(lens_uses)")}
        assert columns == {"id", "lens_id", "question", "said", "facets", "corrected", "at"}
        dump = "\n".join(
            "|".join(str(cell) for cell in row)
            for table in ("lens_uses", "lenses")
            for row in db.execute(f"SELECT * FROM {table}")
        )
    for who in (SHEN, CHEN):
        assert who not in dump and who.split("@")[0] not in dump
    assert cid_shen not in dump
    # Only the day is kept, not the hour.
    assert all(len(u["at"]) == 10 for u in shown)
    # Nor does the person's own page of handoffs know of it.
    assert scene.page(wang)["waiting"] == []


def test_a_use_in_another_lens_is_not_the_persons_to_correct_and_a_correction_is_remembered(scene: Team) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    ask_lens(scene, SHEN, lens_id)
    [use] = scene.team.lens_uses(lens_id)
    scene.as_(WANG)
    corrected = scene.web.post(f"/api/persona/lenses/{lens_id}/uses/{use.id}/correct", headers=wang.headers)
    assert corrected.status_code == 200 and corrected.json()["use"]["corrected"] is True
    assert scene.web.post(f"/api/persona/lenses/{lens_id}/uses/nope/correct", headers=wang.headers).status_code == 404
    assert scene.web.post(f"/api/persona/lenses/nope/uses/{use.id}/correct", headers=wang.headers).status_code == 404
    other = made(scene, ["2.3"], name="另一个赋能")
    crossed = scene.web.post(f"/api/persona/lenses/{other}/uses/{use.id}/correct", headers=wang.headers)
    assert crossed.status_code == 404
    assert [
        u["corrected"]
        for u in scene.web.get(f"/api/persona/lenses/{lens_id}/uses", headers=wang.headers).json()["uses"]
    ] == [True]


def test_a_facet_corrected_three_times_is_no_longer_used_until_it_is_opened_again(scene: Team) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    for _ in range(STOP_AFTER):
        assert ask_lens(scene, SHEN, lens_id).json()["lens"]["views"]
    scene.as_(WANG)
    uses = scene.web.get(f"/api/persona/lenses/{lens_id}/uses", headers=wang.headers).json()["uses"]
    for use in uses[: STOP_AFTER - 1]:
        sent = scene.web.post(f"/api/persona/lenses/{lens_id}/uses/{use['id']}/correct", headers=wang.headers)
        assert sent.json()["lens"]["stopped"] == []
    last = scene.web.post(f"/api/persona/lenses/{lens_id}/uses/{uses[-1]['id']}/correct", headers=wang.headers).json()
    assert last["lens"]["stopped"] == [{"facet_id": "3.4", "name": "常见取舍", "corrected": STOP_AFTER}]
    assert last["lens"]["speaking"] == ["2.3"]
    # It is not used any more, and the other facet still is.
    assert ask_lens(scene, SHEN, lens_id).json()["lens"]["views"] == []
    # Opening it again starts the count afresh.
    scene.as_(WANG)
    reopened = scene.web.patch(
        f"/api/persona/lenses/{lens_id}", json={"facets": ["2.3", "3.4"], "reopen": ["3.4"]}, headers=wang.headers
    )
    assert reopened.status_code == 200 and reopened.json()["stopped"] == []
    assert reopened.json()["speaking"] == ["2.3", "3.4"]
    assert ask_lens(scene, SHEN, lens_id).json()["lens"]["views"]
    # Renaming it leaves the corrections as they are.
    scene.as_(WANG)
    again = scene.web.patch(f"/api/persona/lenses/{lens_id}", json={"name": "改了名字"}, headers=wang.headers)
    assert again.json()["name"] == "改了名字" and again.json()["stopped"] == []


def test_a_facet_corrected_out_stays_out_however_often_the_scope_is_saved_until_it_is_opened_afresh(
    scene: Team,
) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    for _ in range(STOP_AFTER):
        ask_lens(scene, SHEN, lens_id)
    for use in scene.team.lens_uses(lens_id):
        scene.team.correct_lens_use(use.id)
    stopped = [{"facet_id": "3.4", "name": "常见取舍", "corrected": STOP_AFTER}]
    for _ in range(3):
        scene.as_(WANG)
        saved = scene.web.patch(
            f"/api/persona/lenses/{lens_id}",
            json={"name": "大客户谈判", "facets": ["2.3", "3.4"]},
            headers=wang.headers,
        )
        assert saved.status_code == 200
        assert saved.json()["stopped"] == stopped and saved.json()["speaking"] == ["2.3"]
        assert [f["facet_id"] for f in saved.json()["facets"]] == ["2.3", "3.4"]
    assert ask_lens(scene, SHEN, lens_id).json()["lens"]["views"] == []
    # Named in ``reopen`` it is opened afresh, and the count starts again.
    scene.as_(WANG)
    reopened = scene.web.patch(
        f"/api/persona/lenses/{lens_id}", json={"facets": ["2.3", "3.4"], "reopen": ["3.4"]}, headers=wang.headers
    )
    assert reopened.json()["stopped"] == [] and reopened.json()["speaking"] == ["2.3", "3.4"]


def test_a_facet_corrected_out_taken_out_and_put_back_starts_its_count_afresh(scene: Team) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    for _ in range(STOP_AFTER):
        ask_lens(scene, SHEN, lens_id)
    for use in scene.team.lens_uses(lens_id):
        scene.team.correct_lens_use(use.id)
    scene.as_(WANG)
    assert [f["facet_id"] for f in lenses_of(scene)["lenses"][0]["stopped"]] == ["3.4"]
    scene.as_(WANG)
    taken_out = scene.web.patch(f"/api/persona/lenses/{lens_id}", json={"facets": ["2.3"]}, headers=wang.headers)
    assert taken_out.status_code == 200 and taken_out.json()["stopped"] == []
    put_back = scene.web.patch(f"/api/persona/lenses/{lens_id}", json={"facets": ["2.3", "3.4"]}, headers=wang.headers)
    assert put_back.status_code == 200
    assert put_back.json()["stopped"] == [] and put_back.json()["speaking"] == ["2.3", "3.4"]
    assert ask_lens(scene, SHEN, lens_id).json()["lens"]["views"]


def test_a_lens_is_taken_back_when_its_person_says_it_is_not_them_and_the_next_one_does_not_inherit_it(
    scene: Team,
) -> None:
    lens_id = made(scene)
    held = made(scene, ["2.3"], name="另一个赋能")
    scene.as_(WANG)
    scene.web.post(f"/api/persona/lenses/{held}/pause", headers=scene.twins["wang"].headers)
    assert ask_lens(scene, SHEN, lens_id).status_code == 200
    scene.as_(WANG)
    assert scene.web.post(f"/api/personas/{scene.twins['wang'].persona}/disown", headers=CSRF).status_code == 200
    assert {lens.status for lens in scene.team.lenses(persona_id=scene.twins["wang"].persona)} == {"withdrawn"}
    # The administrator gives it to someone else, who takes it: nothing the first person lent is lent now.
    successor = "next@xjjk.com"
    scene.login(successor)
    scene.as_(ADMIN)
    claim = scene.web.put(f"/api/personas/{scene.twins['wang'].persona}/claim", json={"claim": successor}, headers=CSRF)
    assert claim.status_code == 200
    scene.as_(successor)
    scene.web.get("/api/personas")
    approved = scene.web.post(
        f"/api/personas/{scene.twins['wang'].persona}/approve", json={"public": True}, headers=CSRF
    )
    assert approved.status_code == 200
    scene.as_(SHEN)
    available = scene.web.get("/api/persona/lenses/available", headers=scene.twins["wang"].headers)
    assert available.json() == {"lenses": []}
    assert ask_lens(scene, SHEN, lens_id).status_code == 404


def test_the_words_of_a_rejected_item_the_person_keeps_to_themself_stay_hidden(
    scene: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    import twin.lenses
    from twin.persona.items import PReview
    from twin.persona.schema import ReviewStatus

    with PersonaStore(scene.twins["wang"].path) as store:
        store.set_review("pi_family", PReview(status=ReviewStatus.REJECTED, reviewed_at="2026-10-01"))
        private = {
            ev.expression_id
            for i in store.list_items(include_rejected=True)
            if i.item_id == "pi_family"
            for ev in i.evidence
        }
    seen: list[Any] = []
    speak, sample = twin.lenses.speak, twin.lenses.sample

    def spy_speak(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs["hidden"])
        return speak(*args, **kwargs)

    def spy_sample(items: Any, facets: Any, hidden: Any = ()) -> Any:
        seen.append(hidden)
        return sample(items, facets, hidden)

    monkeypatch.setattr(twin.lenses, "speak", spy_speak)
    monkeypatch.setattr(twin.lenses, "sample", spy_sample)
    lens_id = made(scene)
    assert ask_lens(scene, SHEN, lens_id).status_code == 200
    scene.as_(WANG)
    shown = scene.web.post("/api/persona/lenses/preview", json={"facets": ["3.4"]}, headers=scene.twins["wang"].headers)
    assert shown.status_code == 200
    # Rejecting it does not open its words, in an answer or a preview.
    assert len(seen) == 2 and private and all(private <= set(hidden.ids) for hidden in seen)


def test_the_uses_of_one_facet_can_be_looked_at(scene: Team) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    ask_lens(scene, SHEN, lens_id)
    ask_lens(scene, SHEN, lens_id, "答应客户的事做不到怎么办？")
    scene.as_(WANG)
    only = scene.web.get(f"/api/persona/lenses/{lens_id}/uses?facet=2.3", headers=wang.headers).json()["uses"]
    assert [u["facets"][0]["facet_id"] for u in only] == ["2.3"]


# ------------------------------------------------------------------ asking the person themself


def test_a_colleague_who_wants_the_persons_own_answer_asks_in_their_own_name_apart_from_the_use(scene: Team) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    cid = scene.conversation(SHEN, wang)
    assert ask_lens(scene, SHEN, lens_id, conversation=cid).status_code == 200
    assert scene.team.handoffs() == []  # the lens never hands anything over by itself
    scene.as_(SHEN)
    sent = scene.web.post("/api/persona/lenses/ask-owner", json={"conversation_id": cid}, headers=wang.headers)
    assert sent.status_code == 200, sent.text
    [handoff] = scene.team.handoffs()
    assert (handoff.asker, handoff.conversation_id, handoff.question) == (SHEN, cid, PRICE_QUESTION)
    # The person sees it as any colleague's question, with who asked; the use of the lens still says nothing of it.
    page = scene.page(wang)
    assert [w["question"] for w in page["waiting"]] == [PRICE_QUESTION]
    [use] = scene.team.lens_uses(lens_id)
    assert not hasattr(use, "asker") and handoff.id not in repr(use) and cid not in repr(use)
    # Once only, and not for someone else's conversation.
    scene.as_(SHEN)
    again = scene.web.post("/api/persona/lenses/ask-owner", json={"conversation_id": cid}, headers=wang.headers)
    assert again.status_code == 409
    scene.as_(CHEN)
    other = scene.web.post("/api/persona/lenses/ask-owner", json={"conversation_id": cid}, headers=wang.headers)
    assert other.status_code == 404
    scene.as_(WANG)
    assert (
        scene.web.post("/api/persona/lenses/ask-owner", json={"conversation_id": cid}, headers=wang.headers).status_code
        == 403
    )


def test_asking_the_person_from_a_conversation_the_assistant_asked_in_ones_name_is_refused(scene: Team) -> None:
    lens_id = made(scene)
    wang = scene.twins["wang"]
    cid = scene.conversation(SHEN, wang)
    assert ask_lens(scene, SHEN, lens_id, conversation=cid).status_code == 200
    with scene.team._tx() as db:  # asked by Shen's assistant in his name (代问)
        db.execute("UPDATE conversations SET via = 'delegate' WHERE id = ?", (cid,))
    scene.as_(SHEN)
    refused = scene.web.post("/api/persona/lenses/ask-owner", json={"conversation_id": cid}, headers=wang.headers)
    assert refused.status_code == 409 and "转给本人" in refused.json()["detail"]
    assert scene.team.handoffs() == []


# ------------------------------------------------------------------ the database


def test_the_lenses_of_a_twin_that_is_gone_for_good_go_with_it(scene: Team) -> None:
    lens_id = made(scene)
    ask_lens(scene, SHEN, lens_id)
    scene.team.forget_persona(scene.twins["wang"].persona)
    assert scene.team.get_lens(lens_id) is None and scene.team.get_lens_use("x") is None
    with sqlite3.connect(scene.team.path) as db:
        assert db.execute("SELECT COUNT(*) FROM lens_uses").fetchone()[0] == 0


def test_the_unauthenticated_cannot_reach_a_lens(scene: Team) -> None:
    made(scene)
    scene.web.cookies.clear()
    response = scene.web.get("/api/persona/lenses", headers={**CSRF, "X-Twin-Persona": scene.twins["wang"].persona})
    assert response.status_code == 401
