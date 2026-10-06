"""Optional questions that help a personal twin get to know its owner."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from ..config import Settings
from .dimensions import FACET_BY_ID
from .schema import ParsedSource
from .sources import parse_questionnaire
from .store import PersonaStore

QUESTIONNAIRE_VERSION = "q-v1"
MAX_ANSWER_CHARS = 4000

Round = Literal["initial"]
QuestionKind = Literal["open", "situation", "preference"]
KIND_LABELS: dict[QuestionKind, str] = {"open": "开放", "situation": "情境", "preference": "偏好"}


@dataclass(frozen=True)
class Question:
    number: int
    section: str
    text: str
    kind: QuestionKind
    facets: tuple[str, ...]
    optional: bool = True

    @property
    def qid(self) -> str:
        return f"q{self.number:02d}"


def _q(n: int, section: str, text: str, facets: str, kind: QuestionKind = "open") -> Question:
    return Question(n, section, text, kind, tuple(facets.split()))


S1, S2, S3, S4, S5, S6, S7, S8, S9 = (
    "经历与身份",
    "看重什么",
    "怎么做决定",
    "怎么思考",
    "擅长什么",
    "说话方式",
    "和人相处",
    "最近在关注",
    "生活与喜好",
)

QUESTIONS: tuple[Question, ...] = (
    _q(1, S1, "你会怎样介绍自己？可以说说现在住在哪里、平时在做什么。", "1.1 1.4"),
    _q(2, S1, "哪段经历对你的影响比较大？发生了什么，给你留下了什么？", "1.2 1.3"),
    _q(3, S2, "生活里你最看重什么？可以举一件让你觉得值得的事。", "2.1 2.3"),
    _q(4, S2, "有什么事你不愿意做，或者不愿意为了别的东西放弃？", "2.2 2.4"),
    _q(5, S3, "最近做过一个什么选择？你考虑了哪些事，最后为什么这样选？", "3.1 3.2 3.4"),
    _q(6, S3, "拿不定主意时，你会查资料、问别人，还是听自己的感觉？", "3.3 3.6"),
    _q(7, S3, "有没有一个话题你一直有自己的看法？你为什么这样想？", "3.5"),
    _q(8, S4, "遇到一个不熟悉的问题，你通常从哪里开始想？举个小例子就好。", "4.1 4.2"),
    _q(9, S4, "遇到和预想不一样的结果，你通常会怎么弄明白？", "4.3 4.4"),
    _q(10, S5, "有什么事你比较拿手，或者别人常来问你？", "5.1 5.2"),
    _q(11, S5, "有没有你不太懂但想了解的东西？不知道答案时你会怎么办？", "5.3"),
    _q(12, S6, "你常用哪些词或口头禅？写几句你平时会说的话。", "6.1 6.2 6.3"),
    _q(13, S6, "朋友约你周末出去，但你想在家休息。你会怎么回复？直接写原话。", "6.4 6.5", "situation"),
    _q(14, S7, "和熟悉的人、不熟悉的人相处时，你有什么不一样？", "7.1 7.3"),
    _q(15, S7, "和人意见不同时，你通常怎么说、怎么做？对方需要帮助时呢？", "7.2 7.4"),
    _q(16, S7, "什么容易让你着急？压力大时，你会怎样让自己缓过来？", "7.5"),
    _q(17, S8, "最近有什么事占了你比较多的时间或心思？现在怎么样了？", "8.1 8.2"),
    _q(18, S8, "最近有什么想尝试的事，或者还没想清楚的问题？", "8.3"),
    _q(19, S9, "有空时你喜欢做什么？最近喜欢的书、音乐、食物或地方是什么？", "9.1 9.5"),
    _q(20, S9, "你平时怎样安排休息、运动和日常生活？家里有没有你愿意分享的事？", "9.2 9.3 9.4"),
)


def questions_of(round_: Round) -> list[Question]:
    return list(QUESTIONS)


class RoundState(BaseModel):
    round: Round
    version: str = QUESTIONNAIRE_VERSION
    status: Literal["empty", "draft", "submitted"] = "empty"
    answers: dict[str, str] = Field(default_factory=dict)
    updated_at: str | None = None
    submitted_at: str | None = None
    source_id: str | None = None


def _key(round_: Round) -> str:
    return f"questionnaire:{round_}"


def load_round(store: PersonaStore, round_: Round) -> RoundState:
    raw = store.get_meta(_key(round_))
    state = RoundState.model_validate_json(raw) if raw else RoundState(round=round_)
    if state.version != QUESTIONNAIRE_VERSION:
        # Keep the imported source, but never put old answers under different questions.
        return RoundState(round=round_, source_id=state.source_id)
    return state


def clean_answers(round_: Round, answers: dict[str, str]) -> dict[str, str]:
    allowed = {q.qid for q in questions_of(round_)}
    unknown = sorted(set(answers) - allowed)
    if unknown:
        raise ValueError(f"没有这些题目：{'、'.join(unknown)}")
    cleaned = {k: v.strip() for k, v in answers.items() if v.strip()}
    too_long = [k for k, v in cleaned.items() if len(v) > MAX_ANSWER_CHARS]
    if too_long:
        raise ValueError(f"单题回答不能超过 {MAX_ANSWER_CHARS} 字：{'、'.join(too_long)}")
    return cleaned


def save_draft(store: PersonaStore, round_: Round, answers: dict[str, str]) -> RoundState:
    state = load_round(store, round_)
    state.answers = clean_answers(round_, answers)
    state.status = "draft" if state.status != "submitted" else "submitted"
    state.updated_at = dt.datetime.now().isoformat(timespec="seconds")
    store.set_meta(_key(round_), state.model_dump_json())
    return state


def render_markdown(answers: dict[str, str]) -> str:
    lines: list[str] = []
    section = ""
    for q in QUESTIONS:
        if q.section != section:
            section = q.section
            lines += [f"### {section}", ""]
        mark = "【可跳过】" if q.optional else ""
        lines += [f"**{q.number}.{mark}{q.text}**　*{KIND_LABELS[q.kind]} · {' '.join(q.facets)}*", ""]
        lines += [f"回答：{answers.get(q.qid, '')}", ""]
    return "\n".join(lines)


def submit_initial(store: PersonaStore, settings: Settings, answers: dict[str, str]) -> ParsedSource:
    state = load_round(store, "initial")
    cleaned = clean_answers("initial", answers)
    if not cleaned:
        raise ValueError("还没有回答任何问题")
    today = dt.date.today()
    parsed = parse_questionnaire(f"在线问卷_{today.isoformat()}.md", render_markdown(cleaned), settings, today)
    if state.source_id and state.source_id != parsed.source.source_id:
        store.delete_source(state.source_id)
    store.put_source(parsed)
    now = dt.datetime.now().isoformat(timespec="seconds")
    state.answers, state.status, state.updated_at, state.submitted_at = cleaned, "submitted", now, now
    state.source_id = parsed.source.source_id
    store.set_meta(_key("initial"), state.model_dump_json())
    return parsed


def round_view(store: PersonaStore, round_: Round) -> dict[str, object]:
    state = load_round(store, round_)
    return {
        **json.loads(state.model_dump_json()),
        "questions": [
            {
                "id": q.qid,
                "number": q.number,
                "section": q.section,
                "text": q.text,
                "kind": KIND_LABELS[q.kind],
                "facets": [f"{f} {FACET_BY_ID[f].name}" for f in q.facets],
                "optional": q.optional,
            }
            for q in questions_of(round_)
        ],
    }
