"""The 建档问卷 (profile questionnaire), answered in the web UI.

Rounds: ``initial`` (all questions; submitting imports the answers as a questionnaire source, so the profile parser
and its rules apply: test questions are held out, a skipped optional question declines its facets) and ``retest``
(the test questions again, some weeks later, for the person's own test-retest consistency). Drafts and submissions
are kept in the persona store's meta table.
"""

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

QUESTIONNAIRE_VERSION = "q-v0"
RETEST_AFTER_DAYS = 21
MAX_ANSWER_CHARS = 4000

Round = Literal["initial", "retest"]
QuestionKind = Literal["open", "situation", "preference"]
KIND_LABELS: dict[QuestionKind, str] = {"open": "开放", "situation": "情境", "preference": "偏好"}


@dataclass(frozen=True)
class Question:
    number: int
    section: str
    text: str
    kind: QuestionKind
    facets: tuple[str, ...]
    test: bool = False
    optional: bool = False

    @property
    def qid(self) -> str:
        return f"q{self.number:02d}"


def _q(
    n: int, section: str, text: str, kind: QuestionKind, facets: str, *, test: bool = False, optional: bool = False
) -> Question:
    return Question(n, section, text, kind, tuple(facets.split()), test, optional)


S1, S2, S3, S4, S5, S6, S7, S8, S9 = (
    "身份与经历",
    "价值观与原则",
    "决策与判断",
    "思维方式",
    "知识与专长",
    "表达风格",
    "人际与情绪",
    "当前状态与关注",
    "个人生活与偏好（均可跳过）",
)

QUESTIONS: tuple[Question, ...] = (
    _q(1, S1, "用三五句话介绍你现在的角色：负责什么、向谁汇报、谁向你汇报。", "open", "1.1 1.4"),
    _q(2, S1, "职业经历里对你影响最大的两三次转折是什么？当时发生了什么，你从中得出了什么结论？", "open", "1.2"),
    _q(3, S1, "有没有一个你经常讲给团队听的故事或经历？请按你平时讲的样子写下来。", "open", "1.3 6.3"),
    _q(
        4,
        S2,
        "把下面几项按你实际做事时的优先级排序：结果、速度、质量、成本、团队成长、客户满意、合规。排完说一句为什么第一位是它。",
        "preference",
        "2.1",
    ),
    _q(5, S2, "什么事你一定不会做，或者一定不允许团队做？举一个真实发生过的例子。", "open", "2.2"),
    _q(
        6,
        S2,
        "一个能力很强但经常不守流程的下属，这次又绕过流程把事情办成了，结果很好。你会怎么处理？写出你会对他说的话。",
        "situation",
        "2.4 7.2",
    ),
    _q(7, S2, "你常挂在嘴边的做事原则有哪些？写三条，用你自己的原话。", "open", "2.3 6.1"),
    _q(
        8,
        S3,
        "一个新项目，你判断有六成把握能成，成了收益很大，失败会损失一个季度的预算。投不投？写出你拍板时会说的话。",
        "situation",
        "3.1",
    ),
    _q(
        9,
        S3,
        "今年的考核指标，和一件对两三年后很重要、但今年见不到效果的事，抢同一批人。你怎么分？",
        "situation",
        "3.2 3.4",
    ),
    _q(
        10,
        S3,
        "数据显示方案 A 更好，但你的直觉和经验都觉得 B 更对。你怎么决定？有真实发生过的例子最好。",
        "situation",
        "3.3",
    ),
    _q(11, S3, "下属来汇报一个方案，需要你当场表态，但你觉得信息还不够。你通常会怎么说？", "situation", "3.6 6.2"),
    _q(
        12,
        S3,
        "在你负责的领域里，有哪些事你有明确立场？比如自研还是外采、扩张还是收缩、标准化还是定制。写两三个，说明立场和理由。",
        "open",
        "3.5",
    ),
    _q(
        13,
        S3,
        "合作方提出一个大单，条件是为他单独定制一个功能，交付周期很紧。你听完汇报，第一句会说什么？最后怎么定？",
        "situation",
        "3.4 3.6",
        test=True,
    ),
    _q(
        14,
        S3,
        "团队提议引入一个新工具或新流程，能提效，但所有人都要改习惯，迁移期会拖慢两周。你怎么决定？写出你会说的话。",
        "situation",
        "3.1 3.6",
        test=True,
    ),
    _q(
        15,
        S4,
        "下属给你看一份汇报，结论是“项目进展顺利”。你最可能先问哪三个问题？按你会问的顺序写。",
        "situation",
        "4.2",
    ),
    _q(16, S4, "面对一个复杂的新问题，你通常怎么拆？用最近遇到的一个真实问题说明。", "open", "4.1"),
    _q(17, S4, "你常用哪些比喻、类比或“说白了就是……”这类说法来讲道理？写两三个。", "open", "4.3 6.3"),
    _q(
        18,
        S4,
        "一个指标突然比上月好了 30%，团队很兴奋。你会怎么反应？写出你会说的话。",
        "situation",
        "4.2 4.4",
        test=True,
    ),
    _q(19, S5, "你最有把握的两三个专业领域是什么？在这些领域里，你有什么和多数人不一样的判断？", "open", "5.1 5.2"),
    _q(20, S5, "你对所在行业未来两三年最重要的一个判断是什么？为什么？", "open", "5.2"),
    _q(21, S5, "下属问你一个你不熟悉领域的技术选型问题，等你拍板。你会怎么回？写原话。", "situation", "5.3 4.4"),
    _q(
        22,
        S6,
        "下属在工作群里说“这周的版本要延期三天”。用你平时的口气回复，直接写你会发的原话。",
        "situation",
        "6.1 6.2 7.2",
    ),
    _q(23, S6, "同一件事（项目延期三天），你会怎么向你的上级汇报？写原话。", "situation", "6.4 7.1"),
    _q(
        24,
        S6,
        "同一个通知（下周起每周一早上开例会），分别写一版你会在会上口头说的，和一版你会发的邮件。",
        "situation",
        "6.5",
    ),
    _q(25, S6, "外部合作伙伴发消息催一个你们还没准备好的交付。你会怎么回？写原话。", "situation", "6.4 7.3", test=True),
    _q(26, S7, "你的上级在会上当众否定了你认为对的方案。会上你怎么说，会后你怎么做？", "situation", "7.1 7.4"),
    _q(27, S7, "一个下属犯了一个不小的错，但他已经在补救。你会怎么跟他谈？写出你会说的话。", "situation", "7.2"),
    _q(
        28,
        S7,
        "两个平级部门为了资源争执不下，找你评理。你怎么处理？写出你会说的话。",
        "situation",
        "7.3 7.4",
        test=True,
    ),
    _q(29, S7, "什么情况最容易让你着急或生气？压力大的时候，你会有什么变化，身边的人能看出来吗？", "open", "7.5"),
    _q(
        30,
        S7,
        "一个你很看好的下属提出离职。你第一反应是什么，会怎么谈？写出你会说的话。",
        "situation",
        "7.2 7.5",
        test=True,
    ),
    _q(31, S8, "这个季度你最重要的三件事是什么？各自进展如何？", "open", "8.1 8.2"),
    _q(32, S8, "最近有什么事让你在纠结、还没想清楚？", "open", "8.3"),
    _q(33, S9, "工作之外你喜欢做什么？最近一次投入很多时间的爱好是什么？", "open", "9.1", optional=True),
    _q(34, S9, "你的作息和生活习惯大概是怎样的？比如几点起、怎么运动、怎么休息。", "open", "9.2 9.4", optional=True),
    _q(35, S9, "最近在读、在看或在听什么？喜欢什么口味的食物？", "open", "9.5", optional=True),
    _q(36, S9, "家庭方面，有没有你愿意让分身知道的内容？例如家里有几口人、近期的大事。", "open", "9.3", optional=True),
)
QUESTION_BY_ID: dict[str, Question] = {q.qid: q for q in QUESTIONS}


def questions_of(round_: Round) -> list[Question]:
    return [q for q in QUESTIONS if round_ == "initial" or q.test]


class RoundState(BaseModel):
    round: Round
    version: str = QUESTIONNAIRE_VERSION
    status: Literal["empty", "draft", "submitted"] = "empty"
    answers: dict[str, str] = Field(default_factory=dict)
    updated_at: str | None = None
    submitted_at: str | None = None
    # The questionnaire source the submitted initial round was imported as.
    source_id: str | None = None


def _key(round_: Round) -> str:
    return f"questionnaire:{round_}"


def load_round(store: PersonaStore, round_: Round) -> RoundState:
    raw = store.get_meta(_key(round_))
    return RoundState.model_validate_json(raw) if raw else RoundState(round=round_)


def clean_answers(round_: Round, answers: dict[str, str]) -> dict[str, str]:
    """Answers to this round's questions only, trimmed; empty ones dropped. Raises ValueError on an unknown question
    or an answer that is too long."""
    allowed = {q.qid for q in questions_of(round_)}
    unknown = sorted(set(answers) - allowed)
    if unknown:
        raise ValueError(f"不属于这一轮的题目：{'、'.join(unknown)}")
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
    """The initial round in the format ``parse_questionnaire`` reads, so web answers and an exported questionnaire
    document go through the same rules."""
    lines: list[str] = []
    section = ""
    for q in QUESTIONS:
        if q.section != section:
            section = q.section
            lines += [f"### {section}", ""]
        mark = "【测试题】" if q.test else "【可跳过】" if q.optional else ""
        lines += [f"**{q.number}.{mark}{q.text}**　*{KIND_LABELS[q.kind]} · {' '.join(q.facets)}*", ""]
        lines += [f"回答：{answers.get(q.qid, '')}", ""]
    return "\n".join(lines)


def submit_initial(store: PersonaStore, settings: Settings, answers: dict[str, str]) -> ParsedSource:
    """Import questionnaire answers via ``put_source``, replacing an earlier submission's source."""
    state = load_round(store, "initial")
    cleaned = clean_answers("initial", answers)
    if not any(not QUESTION_BY_ID[k].test for k in cleaned):
        raise ValueError("还没有回答任何建档题目")
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


def submit_retest(store: PersonaStore, answers: dict[str, str]) -> RoundState:
    if load_round(store, "initial").status != "submitted":
        raise ValueError("请先提交第一轮问卷，再做重测")
    cleaned = clean_answers("retest", answers)
    if not cleaned:
        raise ValueError("还没有回答任何测试题")
    state = load_round(store, "retest")
    now = dt.datetime.now().isoformat(timespec="seconds")
    state.answers, state.status, state.updated_at, state.submitted_at = cleaned, "submitted", now, now
    store.set_meta(_key("retest"), state.model_dump_json())
    return state


def round_view(store: PersonaStore, round_: Round) -> dict[str, object]:
    state = load_round(store, round_)
    initial = load_round(store, "initial") if round_ == "retest" else state
    retest_from = None
    if initial.submitted_at:
        retest_from = (dt.datetime.fromisoformat(initial.submitted_at) + dt.timedelta(days=RETEST_AFTER_DAYS)).date()
    return {
        **json.loads(state.model_dump_json()),
        "retest_from": retest_from.isoformat() if retest_from else None,
        "questions": [
            {
                "id": q.qid,
                "number": q.number,
                "section": q.section,
                "text": q.text,
                "kind": KIND_LABELS[q.kind],
                "facets": [f"{f} {FACET_BY_ID[f].name}" for f in q.facets],
                "test": q.test,
                "optional": q.optional,
            }
            for q in questions_of(round_)
        ],
    }
