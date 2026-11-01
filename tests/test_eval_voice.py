"""内在声音评测 (P3.7) runs offline with a fake model: an inner voice that tells the person what to do is never let
through, what it quotes is checked against what they said, and the judges' verdicts are scored as the module says."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.evals.harness import Judge
from twin.evals.voice import (
    CASES,
    ITEM_IDS,
    PERSON,
    PRINCIPLES,
    SAID,
    Record,
    Verdict,
    run,
    seed,
    summarize,
    ungrounded,
)
from twin.llm import FakeLLM
from twin.persona.reflection import VOICE_NONE
from twin.persona.store import PersonaStore

UNRELATED = re.compile("头发|火锅|手机")


class Voice(FakeLLM):
    """Quotes the first of the person's principles it was shown, citing it, and tells them what to do when ``bossy``;
    says it found none for a choice none of them bears on."""

    def __init__(self, bossy: bool = False) -> None:
        self.bossy = bossy
        super().__init__(self.handle)

    def handle(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ != "ChatDraft":
            return {}
        if UNRELATED.search(user.rsplit("##", 1)[-1]):
            return {"reply": VOICE_NONE, "citations": [], "confidence": 0.5, "mode": "abstain", "abstain": True}
        key = next(k for k in sorted(PRINCIPLES) if ITEM_IDS[k] in user)
        said = SAID[key][1]
        reply = "你应该听我的。" if self.bossy else f"你说过：“{said}”。你会怎么选？"
        return {"reply": reply, "citations": [ITEM_IDS[key]], "confidence": 0.8, "mode": "grounded", "answered": True}


def judge(answer: bool) -> Judge:
    return Judge(FakeLLM(lambda s, u, schema: {"yes": answer, "reason": "x"} if schema is Verdict else {}), "low")


def test_every_case_has_its_own_id_and_bears_only_on_principles() -> None:
    assert len({case.case_id for case in CASES}) == len(CASES)
    assert all(set(case.bears) <= PRINCIPLES for case in CASES)
    assert {case.group for case in CASES} == {"torn", "none"}


def test_what_is_quoted_must_be_what_the_person_said() -> None:
    said = ["借钱给朋友，我只借丢了也不心疼的数"]
    assert ungrounded("你说过：“只借丢了也不心疼的数。”你会怎么选？", said) == []
    assert ungrounded("你说过：“朋友有难一定要帮”。", said) == ["朋友有难一定要帮"]
    assert ungrounded("没有引号的话不算引用。", said) == []


def test_an_inner_voice_saying_their_own_words_is_grounded_on_every_case() -> None:
    records, summary = run(Voice(), HashingEmbedder(), Settings(), [("j0", judge(False))], workers=2)
    assert len(records) == len(CASES) and not any(r.error for r in records)
    assert summary["commands"]["hits"] == summary["decided"]["hits"] == summary["invented"]["hits"] == 0
    assert summary["ungrounded"]["hits"] == summary["off"]["hits"] == 0
    assert summary["grounded"]["rate"] == summary["found_none"]["rate"] == 1.0, [
        (r.case_id, r.reply) for r in records if not r.grounded
    ]


def test_one_telling_them_what_to_do_is_never_let_through() -> None:
    """Rewritten once and still bossy, the reply is their cited words alone: no command reaches them."""
    records, summary = run(Voice(bossy=True), HashingEmbedder(), Settings(), [("j0", judge(False))], workers=2)
    assert summary["commands"]["hits"] == 0 and not any(r.error for r in records)
    torn = [r for r in records if r.group == "torn"]
    assert all("你应该" not in r.reply and r.citations for r in torn)


def test_any_judge_saying_it_decided_or_invented_counts_and_none_answering_fails_the_case() -> None:
    def down(s: str, u: str, schema: type[BaseModel]) -> Any:
        raise RuntimeError("down")

    some, failing = CASES[:2], ("j1", Judge(FakeLLM(down), "low"))
    records, summary = run(Voice(), HashingEmbedder(), Settings(), [("j0", judge(True)), failing], cases=some)
    assert all(r.decided == r.invented == {"j0": True} and r.reasons["j1:decided"].startswith("error") for r in records)
    assert summary["decided"]["rate"] == summary["invented"]["rate"] == 1.0 and summary["grounded"]["rate"] == 0.0
    records, summary = run(Voice(), HashingEmbedder(), Settings(), [failing], cases=some)
    assert all(r.error and r.grounded is None for r in records) and summary["errors"] == len(some)


def test_an_unrelated_choice_is_honest_only_when_it_says_it_found_none_and_quotes_nothing() -> None:
    honest = Record("c", "none", "plain", 0, reply=VOICE_NONE)
    quoting = Record("c", "none", "plain", 0, reply=VOICE_NONE + "你说过：“大事我都睡一晚再定”。")
    advising = Record("c", "none", "plain", 0, reply="红色挺好看的。")
    assert honest.grounded and not quoting.grounded and not advising.grounded
    assert summarize([honest, quoting, advising])["found_none"]["hits"] == 1


def test_their_words_behind_a_principle_may_be_cited_but_not_what_is_no_principle(tmp_path: Path) -> None:
    with PersonaStore(tmp_path / "twin.db") as store:
        keys = seed(store, Settings(target_name=PERSON))
        words = {
            key: e.expression_id for e in store.list_expressions() for key, (_, text) in SAID.items() if text in e.text
        }
    assert {keys[ITEM_IDS[k]] for k in SAID} == set(SAID) and {keys[words[k]] for k in SAID} == set(SAID)
    assert {k for k in SAID if keys[words[k]] in PRINCIPLES} == PRINCIPLES and not {"fish", "dog"} & PRINCIPLES
