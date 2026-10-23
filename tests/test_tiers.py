"""Two tiers of memory: defaults per facet, the person's changes, and what a conversation of each tier may use."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import kernel
from twin.persona.chat import PersonaChat, PersonaContext, search_items
from twin.persona.coverage import coverage_report
from twin.persona.dimensions import FACETS, taxonomy_fingerprint
from twin.persona.items import PersonaItem, PEvidence, PReview
from twin.persona.schema import ChatReply, ChatTurn, EvidenceClass, ReviewStatus, SourceKind
from twin.persona.sources import parse_chat, parse_note
from twin.persona.store import PersonaStore
from twin.persona.tiers import (
    COLLEAGUE,
    DEFAULT_TIERS,
    SELF,
    carry_tiers,
    default_tier,
    for_audience,
    item_tier,
    private_expressions,
    usable,
)

# Synthetic markers, one per item: whatever a colleague's conversation is shown must not carry the private ones.
WORK = "ALPHA-WORK-1f"
FAMILY = "SECRET-FAMILY-9a"
OPENED = "OPENED-HEALTH-3c"
CLOSED = "CLOSED-PRINCIPLE-77"
MARKERS = {"pi_work": WORK, "pi_family": FAMILY, "pi_opened": OPENED, "pi_closed": CLOSED}
QUESTION = "你家里和健康、原则、回款是怎么看的？"


def make(item_id: str, facet: str, marker: str, *candidates: str) -> PersonaItem:
    return PersonaItem(
        item_id=item_id,
        facet_id=facet,
        statement=f"他说起过{marker}",
        member_candidate_ids=list(candidates),
        evidence=[
            PEvidence(
                expression_id=f"e_{item_id}",
                source_id="s1",
                source_kind=SourceKind.CHAT,
                evidence_class=EvidenceClass.SELF_REPORT,
                quote=f"原话{marker}",
            )
        ],
    )


def seed(path: Path | str) -> PersonaStore:
    store = PersonaStore(path)
    store.set_meta("built_at", "2026-01-01")
    store.replace_facet_items("2.1", [make("pi_work", "2.1", WORK, "pc_work")])
    store.replace_facet_items("2.2", [make("pi_closed", "2.2", CLOSED, "pc_closed")])
    store.replace_facet_items("9.3", [make("pi_family", "9.3", FAMILY, "pc_family")])
    store.replace_facet_items("9.4", [make("pi_opened", "9.4", OPENED, "pc_opened")])
    store.set_item_tier("pi_closed", "self")  # a work principle the person keeps to themself
    store.set_item_tier("pi_opened", "colleague")  # a health habit they are glad to share
    return store


class Recorder(FakeLLM):
    """Answers citing every record id it is shown, and keeps everything a chat call was shown."""

    def __init__(self, cite: list[str] | None = None, mode: str = "grounded") -> None:
        super().__init__(self.handle)
        self.seen: list[str] = []
        self.cite, self.mode = cite, mode

    def meta(self, user: str) -> dict[str, Any]:
        cited = self.cite if self.cite is not None else sorted(set(re.findall(r"\[(pi_[a-z]+)\]", user)))
        return {"citations": cited, "confidence": 0.9, "mode": self.mode, "asked": "家人", "answered": True}

    def handle(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ != "ChatDraft":
            return {}
        self.seen += [system, user]
        return {"reply": "我回答了。", **self.meta(system + user)}

    async def stream(self, **kwargs: Any) -> Any:
        self.seen += [kwargs["system"], kwargs["user"]]
        yield "我回"
        yield "答了。\n<<<META>>>\n" + json.dumps(self.meta(kwargs["system"] + kwargs["user"]), ensure_ascii=False)


def chat(store: PersonaStore, llm: FakeLLM, audience: Any) -> PersonaChat:
    return PersonaChat(store, llm, HashingEmbedder(), Settings(target_name="张三"), audience=audience)


def shown(llm: Recorder) -> str:
    return "\n".join(llm.seen)


# ---------------------------------------------------------------- the defaults


def test_every_facet_has_a_default_and_the_personal_ones_start_private() -> None:
    assert set(DEFAULT_TIERS) == {f.facet_id for f in FACETS}
    assert {default_tier(f) for f in ("9.2", "9.3", "9.4")} == {SELF}
    assert {default_tier(f) for f in ("2.1", "3.4", "5.1", "6.2", "7.3")} == {COLLEAGUE}
    assert default_tier("99.9") == SELF  # a facet nobody classified is the person's own
    assert usable(COLLEAGUE, "colleague") and usable(COLLEAGUE, "self") and usable(SELF, "self")
    assert not usable(SELF, "colleague")


def test_the_defaults_are_not_part_of_the_kernel() -> None:
    """Moving a facet between tiers must not make anyone's memories rebuild: the tiers are in neither fingerprint."""
    assert taxonomy_fingerprint() == kernel.TAXONOMY_FINGERPRINTS[kernel.TAXONOMY_VERSION]
    source = Path(kernel.__file__).read_text(encoding="utf-8")
    dimensions = Path(taxonomy_fingerprint.__code__.co_filename).read_text(encoding="utf-8")
    assert "tiers" not in source and "DEFAULT_TIERS" not in dimensions


# ---------------------------------------------------------------- the person's changes


def test_item_tiers_are_the_default_until_the_person_changes_one() -> None:
    with seed(":memory:") as store:
        items = {i.item_id: i for i in store.list_items()}
        tiers = store.item_tiers()
        assert tiers == {"pi_closed": "self", "pi_opened": "colleague"}
        assert {k: item_tier(i, tiers) for k, i in items.items()} == {
            "pi_work": COLLEAGUE,
            "pi_family": SELF,
            "pi_opened": COLLEAGUE,
            "pi_closed": SELF,
        }
        store.set_item_tier("pi_closed", None)  # back to the facet's default
        assert "pi_closed" not in store.item_tiers()
        with pytest.raises(KeyError):
            store.set_item_tier("pi_missing", "self")
        with pytest.raises(ValueError):
            store.set_item_tier("pi_work", "everyone")  # type: ignore[arg-type]


def test_a_tier_survives_the_facet_being_merged_again() -> None:
    with seed(":memory:") as store:
        # The same trait with more evidence keeps the tier; a trait re-extracted under new candidate ids keeps the
        # private tier through the quotes it stands on; an opened one is not guessed at.
        store.replace_facet_items("2.2", [make("pi_closed2", "2.2", CLOSED, "pc_closed", "pc_more")])
        store.replace_facet_items("9.4", [make("pi_opened2", "9.4", OPENED, "pc_new")])
        tiers = store.item_tiers()
        assert tiers.get("pi_closed2") == "self" and "pi_closed" not in tiers
        assert "pi_opened2" not in tiers and "pi_opened" not in tiers
    old = [make("a", "2.1", "x", "pc1"), make("b", "2.1", "y", "pc2")]
    new = [make("c", "2.1", "z", "pc1", "pc2"), make("d", "2.1", "x", "pc9")]
    carried = carry_tiers(old, new, {"a": "colleague", "b": "self"})
    # c continues both, the stricter wins; d was re-extracted from a's expression, which a opened, so it is not guessed.
    assert carried == {"c": "self"}
    new = [make("e", "2.1", "w", "pc7")]
    new[0].evidence[0] = old[1].evidence[0]  # quotes what b stood on
    assert carry_tiers(old, new, {"b": "self"}) == {"e": "self"}
    assert carry_tiers(old, new, {"b": "colleague"}) == {}


def test_a_tier_leaves_with_a_removed_taxonomy_facet(tmp_path: Path) -> None:
    with seed(tmp_path / "twin.db") as store:
        store.replace_facet_items("9.4", [])
        assert "pi_opened" not in store.item_tiers()


def test_listing_counting_and_searching_leave_out_what_the_audience_may_not_use() -> None:
    with seed(":memory:") as store:
        everything, total = store.query_items()
        assert total == 4 and {i.item_id for i in everything} == set(MARKERS)
        for_colleagues, narrowed = store.query_items(audience="colleague")
        assert narrowed == 2 and {i.item_id for i in for_colleagues} == {"pi_work", "pi_opened"}
        assert sum(store.item_counts().values()) == 4 and sum(store.item_counts("colleague").values()) == 2
        assert {i.item_id for i in for_audience(store.list_items(), store.item_tiers(), "colleague")} == {
            "pi_work",
            "pi_opened",
        }
        found = search_items(store, None, "SECRET-FAMILY-9a 家人", 5, "colleague")
        assert FAMILY not in " ".join(i.statement for i in found)
        assert [i.item_id for i in search_items(store, None, "SECRET-FAMILY-9a", 5, "self")] == ["pi_family"]
        report = coverage_report(for_audience(store.list_items(), store.item_tiers(), "colleague"), frozenset())
        assert sum(f.items for f in report.facets) == 2


# ---------------------------------------------------------------- what a conversation is shown


def test_a_colleagues_conversation_is_never_shown_an_item_of_the_persons_own_tier() -> None:
    llm = Recorder()
    with seed(":memory:") as store:
        reply = chat(store, llm, "colleague").reply([ChatTurn(role="user", content=QUESTION)], persist=False)
    prompts = shown(llm)
    for hidden in (FAMILY, CLOSED, "pi_family", "pi_closed"):
        assert hidden not in prompts
    for allowed in (WORK, OPENED):  # the facet default and the item the person opened
        assert allowed in prompts
    assert set(reply.retrieved_ids) == {"pi_work", "pi_opened"} and set(reply.citations) == {"pi_work", "pi_opened"}
    assert FAMILY not in reply.reply


def test_the_persons_own_conversation_can_use_all_of_it() -> None:
    llm = Recorder()
    with seed(":memory:") as store:
        reply = chat(store, llm, "self").reply([ChatTurn(role="user", content=QUESTION)], persist=False)
    prompts = shown(llm)
    assert all(marker in prompts for marker in MARKERS.values())
    assert set(reply.retrieved_ids) == set(MARKERS) and set(reply.citations) == set(MARKERS)


def test_a_chat_that_does_not_say_who_asks_is_a_colleagues() -> None:
    llm = Recorder()
    with seed(":memory:") as store:
        asking = PersonaChat(store, llm, HashingEmbedder(), Settings(target_name="张三"), ledger=True)
        assert asking.audience == COLLEAGUE and not asking.ledger
        asking.reply([ChatTurn(role="user", content=QUESTION)], persist=False)
    assert FAMILY not in shown(llm) and CLOSED not in shown(llm)


def test_the_core_portrait_has_a_colleague_version_and_the_persons_own() -> None:
    with seed(":memory:") as store:
        theirs = PersonaChat(store, Recorder(), HashingEmbedder(), Settings(), audience="colleague")
        mine = PersonaChat(store, Recorder(), HashingEmbedder(), Settings(), audience="self")
        assert {i.item_id for i in theirs.portrait()[0]} == {"pi_work", "pi_opened"}
        assert {i.item_id for i in mine.portrait()[0]} == set(MARKERS)
        ctx = theirs.retrieve(QUESTION)
        assert isinstance(ctx, PersonaContext) and ctx.audience == COLLEAGUE
        assert {i.item_id for i in ctx.core} <= {"pi_work", "pi_opened"}
        assert {i.item_id for i, _ in ctx.items} <= {"pi_work", "pi_opened"} and ctx.items


def test_an_inference_cannot_rest_on_an_item_the_audience_may_not_use() -> None:
    # A model that cites an id it was never shown (here the private family item) gets that citation dropped, and an
    # inference left with nothing to stand on is an abstention.
    llm = Recorder(cite=["pi_family"], mode="inferred")
    with seed(":memory:") as store:
        reply = chat(store, llm, "colleague").reply([ChatTurn(role="user", content=QUESTION)], persist=False)
    assert reply.citations == [] and reply.abstain and reply.mode == "abstain"
    llm = Recorder(cite=["pi_family"], mode="inferred")
    with seed(":memory:") as store:
        reply = chat(store, llm, "self").reply([ChatTurn(role="user", content=QUESTION)], persist=False)
    assert reply.citations == ["pi_family"] and not reply.abstain and reply.mode == "inferred"


def test_the_streamed_answer_is_built_without_the_private_items_too() -> None:
    async def run(audience: Any) -> tuple[Recorder, list[str], ChatReply]:
        llm = Recorder()
        parts: list[str] = []
        final: ChatReply | None = None
        with seed(":memory:") as store:
            async for part in chat(store, llm, audience).stream_reply(
                [ChatTurn(role="user", content=QUESTION)], persist=False
            ):
                if isinstance(part, str):
                    parts.append(part)
                else:
                    final = part
        assert final is not None
        return llm, parts, final

    llm, parts, final = asyncio.run(run("colleague"))
    assert FAMILY not in shown(llm) and CLOSED not in shown(llm) and FAMILY not in "".join(parts)
    assert set(final.retrieved_ids) == {"pi_work", "pi_opened"} and set(final.citations) == {"pi_work", "pi_opened"}
    llm, _, final = asyncio.run(run("self"))
    assert FAMILY in shown(llm) and "pi_family" in final.citations


# ---------------------------------------------------------------- the words behind the items


SAID_PRIVATE = "SECRET-SAID-5d"
SAID_SHARED = "SHARED-SAID-2e"
SAID_OTHERS = "OTHERS-SAID-8b"
CHAT = (
    f"2026-09-01 10:00 张三：我家里的事是{SAID_PRIVATE}\n"
    f"2026-09-01 10:01 张三：回款的事是{SAID_SHARED}\n"
    f"2026-09-01 10:02 李四：你说的家里的事是{SAID_OTHERS}\n"
)


def said_store() -> tuple[PersonaStore, dict[str, str]]:
    """A chat the person's private item and a colleague one stand on, one line each."""
    settings = Settings(target_name="张三")
    store = PersonaStore(":memory:")
    store.put_source(parse_chat("群.txt", CHAT, settings))
    store.set_meta("built_at", "2026-01-01")
    by_text = {e.text: e.expression_id for e in store.list_expressions()}
    ids = {
        key: next(v for t, v in by_text.items() if marker in t)
        for key, marker in (("private", SAID_PRIVATE), ("shared", SAID_SHARED), ("others", SAID_OTHERS))
    }

    def standing(item_id: str, facet: str, *expressions: str) -> PersonaItem:
        return PersonaItem(
            item_id=item_id,
            facet_id=facet,
            statement=f"他说起过 {item_id}",
            evidence=[
                PEvidence(
                    expression_id=e,
                    source_id="s1",
                    source_kind=SourceKind.CHAT,
                    evidence_class=EvidenceClass.SELF_REPORT,
                    quote="x",
                )
                for e in expressions
            ],
        )

    store.replace_facet_items("9.3", [standing("pi_family", "9.3", ids["private"], ids["others"])])
    store.replace_facet_items("2.1", [standing("pi_work", "2.1", ids["shared"])])
    return store, ids


def test_words_only_a_private_item_stands_on_are_the_private_ones() -> None:
    store, ids = said_store()
    with store:
        assert private_expressions(store.list_items(), store.item_tiers()) == {ids["private"], ids["others"]}
        # Opening the item makes its words ordinary; a colleague item standing on the same words keeps them too.
        store.set_item_tier("pi_family", "colleague")
        assert private_expressions(store.list_items(), store.item_tiers()) == set()
        store.set_item_tier("pi_family", "self")
        store.set_item_tier("pi_work", "self")
        assert private_expressions(store.list_items(), store.item_tiers()) == set(ids.values())


def test_a_colleagues_conversation_is_not_shown_the_words_a_private_item_stands_on() -> None:
    store, ids = said_store()
    with store:
        for audience, expected in (("colleague", {SAID_SHARED}), ("self", {SAID_SHARED, SAID_PRIVATE, SAID_OTHERS})):
            llm = Recorder()
            asking = chat(store, llm, audience)
            ctx = asking.retrieve("家里的事和回款的事")
            found = {e.expression_id for e, _ in ctx.expressions} | {e.expression_id for e, _ in ctx.others}
            assert found <= set(ids.values())
            asking.reply([ChatTurn(role="user", content="家里的事和回款的事")], persist=False)
            seen = shown(llm)
            assert {m for m in (SAID_PRIVATE, SAID_SHARED, SAID_OTHERS) if m in seen} == expected, audience
        voice = chat(store, Recorder(), "colleague").portrait()[1]
        assert not any(SAID_PRIVATE in line for line in voice)


def test_the_evidence_shown_to_a_colleague_leaves_out_those_words_too() -> None:
    from twin.web.persona import cited_view

    store, ids = said_store()
    with store:
        refs = [ids["private"], ids["shared"], "pi_family", "pi_work"]
        assert [c["id"] for c in cited_view(store, refs, None, "colleague")] == [ids["shared"], "pi_work"]
        assert [c["id"] for c in cited_view(store, refs, None, "self")] == refs


def test_a_rejected_private_item_keeps_its_words_hidden_and_a_rejected_open_one_opens_none() -> None:
    from twin.web.persona import cited_view

    store, ids = said_store()
    with store:
        store.set_review("pi_family", PReview(status=ReviewStatus.REJECTED, reviewed_at="2026-10-23T10:00:00"))
        everything = store.list_items(include_rejected=True)
        family = next(i for i in everything if i.item_id == "pi_family")
        assert private_expressions(everything, store.item_tiers()) == {ids["private"], ids["others"]}
        llm = Recorder()
        chat(store, llm, "colleague").reply([ChatTurn(role="user", content="家里的事和回款的事")], persist=False)
        assert SAID_PRIVATE not in shown(llm) and SAID_OTHERS not in shown(llm)
        assert [c["id"] for c in cited_view(store, [ids["private"], ids["shared"]], None, "colleague")] == [
            ids["shared"]
        ]
        # An item of the colleague tier the person rejected does not vouch for words a private item stands on.
        rejected = family.model_copy(update={"item_id": "pi_gone", "review": ReviewStatus.REJECTED})
        private = family.model_copy(update={"review": ReviewStatus.UNREVIEWED})
        assert private_expressions([private, rejected], {"pi_family": "self", "pi_gone": "colleague"}) == {
            ids["private"],
            ids["others"],
        }


NOTE_OPEN = "OPEN-NOTE-4b"
NOTE_KEPT = "KEPT-NOTE-6e"


def noted(item_id: str, facet: str, sources: list[str], *candidates: str) -> PersonaItem:
    return PersonaItem(
        item_id=item_id,
        facet_id=facet,
        statement=f"他说起过 {item_id}",
        member_candidate_ids=list(candidates),
        evidence=[
            PEvidence(
                expression_id=f"{s}#00000",
                source_id=s,
                source_kind=SourceKind.DOCUMENT,
                evidence_class=EvidenceClass.SELF_REPORT,
                quote=f"原话 {s}",
            )
            for s in sources
        ],
    )


def test_an_item_that_comes_to_stand_on_a_private_note_is_the_persons_own_round_after_round() -> None:
    settings = Settings(target_name="张三")
    with PersonaStore(":memory:") as store:
        opened, kept = (parse_note(t, settings, f"记一下 {t}") for t in (NOTE_OPEN, NOTE_KEPT))
        for note in (opened, kept):
            store.put_source(note)
        s1, s2 = opened.source.source_id, kept.source.source_id
        store.set_note_tier(s1, COLLEAGUE)
        store.replace_facet_items("9.3", [noted("pi_a", "9.3", [s1], "pc1")])
        assert store.item_tiers() == {"pi_a": COLLEAGUE}  # the opened note opens a private facet's item
        # Merged with a private note's words, the item continuing it (and the colleague tier written for it last
        # round) turns the person's own, and stays so as it is merged again.
        store.set_note_tier(s2, SELF)
        store.replace_facet_items("9.3", [noted("pi_b", "9.3", [s1, s2], "pc1", "pc2")])
        assert store.item_tiers() == {"pi_b": SELF}
        store.replace_facet_items("9.3", [noted("pi_c", "9.3", [s1, s2], "pc1", "pc2", "pc3")])
        assert store.item_tiers() == {"pi_c": SELF}
        # The person's own choice for an item on an opened note is kept: the note only fills in.
        store.replace_facet_items("2.1", [noted("pi_w", "2.1", [s1], "pw1")])
        store.set_item_tier("pi_w", SELF)
        store.replace_facet_items("2.1", [noted("pi_w2", "2.1", [s1], "pw1", "pw2")])
        assert store.item_tiers()["pi_w2"] == SELF


def test_an_item_opened_to_colleagues_does_not_show_them_the_private_note_it_quotes() -> None:
    settings = Settings(target_name="张三")
    with PersonaStore(":memory:") as store:
        note = parse_note(NOTE_KEPT, settings, "记一下")
        store.put_source(note)
        sid = note.source.source_id
        store.set_meta("built_at", "2026-01-01")
        store.replace_facet_items("2.1", [noted("pi_n", "2.1", [sid], "pn")])
        store.set_note_tier(sid, SELF)
        store.set_item_tier("pi_n", COLLEAGUE)  # the person opened the item, not the note
        for audience, quoted in (("colleague", False), ("self", True)):
            llm = Recorder()
            chat(store, llm, audience).reply([ChatTurn(role="user", content="他说起过什么")], persist=False)
            seen = shown(llm)
            assert "pi_n" in seen and (f"原话 {sid}" in seen) is quoted, audience
            assert quoted or NOTE_KEPT not in seen


def test_a_note_tier_is_set_all_at_once_or_not_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(target_name="张三")
    with PersonaStore(":memory:") as store:
        note = parse_note(NOTE_KEPT, settings, "记一下")
        store.put_source(note)
        sid = note.source.source_id
        store.replace_facet_items("2.1", [noted("pi_a", "2.1", [sid], "pa"), noted("pi_b", "2.1", [sid], "pb")])
        assert sorted(store.set_note_tier(sid, SELF)) == ["pi_a", "pi_b"]
        assert store.item_tiers() == {"pi_a": SELF, "pi_b": SELF}

        def broken(*args: Any, **kwargs: Any) -> list[PersonaItem]:
            raise RuntimeError("read failed")

        monkeypatch.setattr(store, "list_items", broken)
        with pytest.raises(RuntimeError):
            store.set_note_tier(sid, COLLEAGUE)
        monkeypatch.undo()
        assert store.note_tiers() == {sid: SELF} and store.item_tiers() == {"pi_a": SELF, "pi_b": SELF}
