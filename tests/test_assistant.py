"""The person's own assistant at the core: what counts as a note, the tier a note gives the memory made from it, the
promise that stands as said, and the prompt only the person's own conversation gets."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import chat as pc
from twin.persona.assistant import NOTE_TITLE, note_text, said_commitment, said_commitment_id
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.schema import EvidenceClass, SourceKind
from twin.persona.sources import parse_note
from twin.persona.store import PersonaStore
from twin.persona.tiers import COLLEAGUE, SELF, PrivateWords, note_item_tier, private_words


def item(item_id: str, facet: str, source_id: str) -> PersonaItem:
    return PersonaItem(
        item_id=item_id,
        facet_id=facet,
        statement=f"他说起过{item_id}",
        evidence=[
            PEvidence(
                expression_id=f"{source_id}#00000",
                source_id=source_id,
                source_kind=SourceKind.DOCUMENT,
                evidence_class=EvidenceClass.SELF_REPORT,
                quote=f"原话{item_id}",
            )
        ],
    )


@pytest.mark.parametrize(
    ("message", "kept"),
    [
        ("记一下，下周三我请假", "下周三我请假"),
        ("记一下下周三我请假", "下周三我请假"),
        ("请记住：我不吃香菜", "我不吃香菜"),
        ("帮我记一下 周五不上班", "周五不上班"),
        ("麻烦你记下来，我对海鲜过敏", "我对海鲜过敏"),
        ("记着，评审在周四", "评审在周四"),
        ("记住我下周二要出差", "我下周二要出差"),
    ],
)
def test_a_message_that_starts_with_the_cue_is_a_note(message: str, kept: str) -> None:
    assert note_text(message) == kept


@pytest.mark.parametrize(
    "message",
    [
        "记得我上周说过什么吗",  # asking whether it remembers
        "我记住了",  # not at the start
        "记一下",  # nothing to remember
        "记一下，",
        "记一下，我周五是不是不上班？",  # a question
        "帮我查一下上周的承诺",
        "",
    ],
)
def test_anything_else_is_not_a_note(message: str) -> None:
    assert note_text(message) is None


def test_a_note_gives_the_items_standing_on_it_its_tier_now_and_later(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    with PersonaStore(tmp_path / "twin.db") as store:
        note = parse_note("下周三请假陪家人复查", settings, f"{NOTE_TITLE} 10-23 09:12")
        store.put_source(note)
        sid = note.source.source_id
        assert store.note_tiers() == {} and store.private_note_sources() == set()
        with pytest.raises(KeyError):
            store.set_note_tier("nope", SELF)
        with pytest.raises(ValueError):
            store.set_note_tier(sid, "all")  # type: ignore[arg-type]

        # Items made from it afterwards take its tier, whatever their facet's default is.
        store.set_note_tier(sid, SELF)
        store.replace_facet_items("2.1", [item("pi_work", "2.1", sid), item("pi_plain", "2.1", "other")])
        store.replace_facet_items("9.3", [item("pi_family", "9.3", sid)])
        assert store.item_tiers() == {"pi_work": SELF, "pi_family": SELF}  # a work facet, kept to themself
        assert store.private_note_sources() == {sid}

        # Changed afterwards, the items already there follow, and the person's own choice for an item is not undone
        # by the next rebuild.
        assert sorted(store.set_note_tier(sid, COLLEAGUE)) == ["pi_family", "pi_work"]
        assert store.item_tiers() == {"pi_work": COLLEAGUE, "pi_family": COLLEAGUE}
        assert store.private_note_sources() == set()
        store.set_item_tier("pi_family", SELF)
        store.replace_facet_items("9.3", [item("pi_family", "9.3", sid)])
        assert store.item_tiers()["pi_family"] == SELF

        # Not kept after all: nothing of it stays, not even the tier.
        assert store.delete_source(sid)
        assert store.note_tiers() == {}


def test_an_item_standing_on_several_notes_is_the_persons_own_if_any_is() -> None:
    mixed = item("pi_a", "2.1", "s1")
    mixed.evidence.append(mixed.evidence[0].model_copy(update={"source_id": "s2", "expression_id": "s2#00000"}))
    assert note_item_tier(mixed, {"s1": COLLEAGUE, "s2": SELF}) == SELF
    assert note_item_tier(mixed, {"s1": COLLEAGUE}) == COLLEAGUE
    assert note_item_tier(mixed, {"other": SELF}) is None


def test_the_words_of_a_private_note_are_hidden_by_their_source_before_any_item_stands_on_them() -> None:
    plain = item("pi_a", "2.1", "s_plain")
    hidden = private_words([plain], {}, {"s_note"})
    assert "s_note#00000" in hidden and "s_note#00007" in hidden
    assert "s_noted#00000" not in hidden and "s_plain#00000" not in hidden and 7 not in hidden
    assert bool(hidden) and not PrivateWords()
    # The words only the person's own items stand on stay hidden as before.
    own = item("pi_b", "9.3", "s_other")
    assert "s_other#00000" in private_words([own], {}, ())


def test_a_promise_said_to_the_assistant_is_a_commitment_that_stands() -> None:
    entry = said_commitment("c1", 4, "我答应王屿周五前给方案", "周五前给王屿发布方案", "王屿", dt.date(2026, 10, 30))
    assert entry.entry_id == said_commitment_id("c1", 4) != said_commitment_id("c1", 6)
    assert entry.origin == "conversation" and entry.kind == "commitment" and entry.status is None
    assert entry.review.value == "confirmed" and entry.owner == "本人" and entry.counterpart == "王屿"
    assert entry.source_id == "said:c1" and entry.quote == "我答应王屿周五前给方案"


def test_only_the_persons_own_conversation_gets_the_assistants_prompt(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", target_name="张三")
    with PersonaStore(tmp_path / "twin.db") as store:
        store.set_meta("built_at", "2026-01-01")
        store.replace_facet_items("2.1", [item("pi_work", "2.1", "s1")])
        llm, embedder = FakeLLM(lambda s, u, sc: {}), HashingEmbedder()
        own = pc.PersonaChat(store, llm, embedder, settings, ledger=True, audience=SELF, assistant=True)
        prompt = pc.chat_system_prompt("张三", own.retrieve("上周答应过谁什么"))
        assert prompt.startswith("你是张三本人的助手，正在和张三自己说话") and "数字分身" not in prompt
        assert "要补一句吗" in prompt and "promise_what" in prompt
        # The twin speaking as the person is the same as ever, for everyone else and for the tier alone.
        for chat in (
            pc.PersonaChat(store, llm, embedder, settings, audience=SELF),
            pc.PersonaChat(store, llm, embedder, settings, audience=COLLEAGUE, assistant=True),
        ):
            assert not chat.assistant
            assert chat_prompt(chat).startswith("你是张三的数字分身")


def chat_prompt(chat: pc.PersonaChat) -> str:
    return pc.chat_system_prompt("张三", chat.retrieve("上周答应过谁什么"))
