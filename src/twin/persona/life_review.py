"""人生回顾: a life told stage by stage, childhood to what it has meant, a question or two at a sitting (docs/
PRODUCT_PERSONA_AGENT.md P1.3). The structure follows life review and dignity therapy interviews; the questions are
our own. An answer goes the way of 补一补 (``persona.fill``): read into draft memories, looked at, kept or not. What
was answered or passed over is kept with the twin, so the next sitting goes on where the last one stopped; a
question passed over comes back once every other has been asked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, Field

from .store import PersonaStore

STAGES: tuple[tuple[str, str], ...] = (
    ("childhood", "童年"),
    ("school", "求学"),
    ("work", "工作"),
    ("family", "家庭"),
    ("loss", "失去"),
    ("meaning", "意义"),
)
STAGE_LABELS = dict(STAGES)
QUESTIONS_PER_SITTING = 2
STATE_KEY = "life_review:state"


@dataclass(frozen=True)
class LifeQuestion:
    question_id: str
    stage: str
    text: str
    # The facets an answer is most likely about, the first the one it is asked for.
    facets: tuple[str, ...]


def _q(n: int, stage: str, text: str, facets: str) -> LifeQuestion:
    return LifeQuestion(f"L{n:02d}", stage, text, tuple(facets.split()))


QUESTIONS: tuple[LifeQuestion, ...] = (
    _q(1, "childhood", "你记得的最早的一件事是什么？那时你几岁，身边有谁？", "1.3 1.2"),
    _q(2, "childhood", "小时候家里是什么样的？那时谁对你影响最大？", "9.3 10.4"),
    _q(3, "childhood", "小时候有什么事让你特别骄傲，或者特别害怕？", "10.3 7.5"),
    _q(4, "school", "上学那些年，有没有哪个人或哪件事改变了你？", "1.2 1.3"),
    _q(5, "school", "那时候你想成为什么样的人？后来呢？", "10.1 2.1"),
    _q(6, "work", "你做过的事情里，哪一段最像你自己？为什么？", "10.3 1.2"),
    _q(7, "work", "有没有一个选择，你到现在还会想起？", "1.2 3.4"),
    _q(8, "family", "你会怎么说你和家人现在的关系？", "9.3 10.4"),
    _q(9, "family", "家人身上有什么，是你希望自己也有，或者不想有的？", "2.1 2.4"),
    _q(10, "loss", "你失去过重要的人或东西吗？那时候你是怎么过来的？", "10.2"),
    _q(11, "loss", "想到变老和离开，你最先想到的是什么？", "10.2"),
    _q(12, "meaning", "回头看，你最希望别人记住你的是什么？", "10.1"),
    _q(13, "meaning", "如果给以后的人留几句话，你会说什么？", "10.1 2.3"),
    _q(14, "meaning", "什么时候你觉得活得最有意思？", "10.3"),
)
QUESTION_BY_ID = {q.question_id: q for q in QUESTIONS}


class LifeReviewState(BaseModel):
    answered: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


def load_state(store: PersonaStore) -> LifeReviewState:
    raw = store.get_meta(STATE_KEY)
    if not raw:
        return LifeReviewState()
    state = LifeReviewState.model_validate(json.loads(raw))
    # A question that is no longer asked is forgotten.
    return LifeReviewState(
        answered=[q for q in state.answered if q in QUESTION_BY_ID],
        skipped=[q for q in state.skipped if q in QUESTION_BY_ID and q not in state.answered],
    )


def _save(store: PersonaStore, state: LifeReviewState) -> None:
    store.set_meta(STATE_KEY, state.model_dump_json())


def mark(store: PersonaStore, question_id: str, *, answered: bool) -> LifeReviewState:
    """Remember that the question was answered (or passed over, until every other has been asked)."""
    state = load_state(store)
    if question_id not in QUESTION_BY_ID or question_id in state.answered:
        return state
    if answered:
        state.answered.append(question_id)
        state.skipped = [q for q in state.skipped if q != question_id]
    elif question_id not in state.skipped:
        state.skipped.append(question_id)
    _save(store, state)
    return state


def next_questions(state: LifeReviewState, limit: int = QUESTIONS_PER_SITTING) -> list[LifeQuestion]:
    """The next questions of the earliest stage not yet told; the ones passed over once nothing else is left."""
    fresh = [q for q in QUESTIONS if q.question_id not in state.answered and q.question_id not in state.skipped]
    if fresh:
        stage = fresh[0].stage
        return [q for q in fresh if q.stage == stage][:limit]
    again = [QUESTION_BY_ID[q] for q in state.skipped]
    return again[:limit]


def progress(state: LifeReviewState) -> list[dict[str, object]]:
    """For each stage, how many of its questions were answered."""
    return [
        {
            "id": stage,
            "label": label,
            "answered": sum(q.question_id in state.answered for q in QUESTIONS if q.stage == stage),
            "total": sum(q.stage == stage for q in QUESTIONS),
        }
        for stage, label in STAGES
    ]
