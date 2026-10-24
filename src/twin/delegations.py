"""Delegation: the person's assistant asks colleagues' twins in their name.

In 我的分身 the person says 帮我问问王屿和陈一：… and their assistant puts the question to those twins, at most
three, one conversation each. The conversations are the person's own (listed as 助手代问) and are answered from the
colleague tier of memory, as if the person had asked. Only the person can start it, and only from their own
conversation with their assistant: a twin that was asked this way never asks another, and the assistant adds nothing of
its own to the question (it promises nothing to anyone). That is one hop, and it is held where the rows are written
(``TeamDB.create_delegation``, ``TeamDB.record_conversation``), not left to the prompts.

What a colleague's twin cannot settle stays with that colleague: the card asks the person whether to hand it to them
(转给本人), and only that press makes the handoff, in the person's name (``HandoffDesk.hand_over``). When an answer
names someone else to ask, the card offers to ask them too (也问问沈从的分身), which is the person's to say.

This module reads what the person said (``parse``) and works out what the person is shown of each answer
(``target_state``, ``mentions``). Putting the questions is the web side's (``web.delegation``).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .teamdb import MAX_DELEGATES

# 帮我问问 / 替我问一下 / 请帮我问问: asking in the person's name, said as an instruction.
CUE = re.compile(
    r"^\s*(?:请你?|麻烦你?|你)?\s*(?:帮我|替我|帮忙|给我)\s*(?:去|先)?\s*问(?:问|一问|一下|下)?[\s，,：:]*"
)
_BETWEEN = re.compile(r"^[\s、，,和与及跟同]+")
_AFTER = re.compile(r"^(?:的分身|本人|他们|俩|两位|三位)?[\s：:，,]*")
_TOKEN = re.compile(r"^[^\s：:，,、]{1,12}")
_COLON = re.compile(r"[：:]")
_SENTENCE_MARKS = re.compile(r"[?？!！。.]")
# The longest a Chinese name is taken to be when no one by that name is known; a name in letters can be longer.
NAME_CHARS = 4
LATIN_NAME_CHARS = 12
# A colon this near the front ends the list of whom to ask.
ADDRESS_CHARS = 40
MIN_QUESTION_CHARS = 2
# After 问 / 找 / 联系 / 咨询 comes a name the answer sends the asker to.
_SEND_TO = "(?:问问?|找|联系|咨询|去问)"
# How the card of one colleague's twin stands.
TargetState = Literal["answered", "needs_owner", "handed", "replied", "skipped"]


@dataclass(frozen=True)
class Asked:
    """What the person asked their assistant to put to colleagues' twins: whom (by the name each is called) and what."""

    names: tuple[str, ...]
    question: str


@dataclass(frozen=True)
class Unclear:
    """The person asked in the way of ``CUE`` but not in a way that can be carried out; ``reply`` says why, to them."""

    reply: str


def _name_like(token: str) -> bool:
    """Whether words that follow the cue could be the name of a colleague: short, and not a sentence."""
    if _SENTENCE_MARKS.search(token):
        return False
    return len(token) <= (LATIN_NAME_CHARS if token.isascii() else NAME_CHARS)


def parse(message: str, known: Mapping[str, Sequence[str]], own: Collection[str] = ()) -> Asked | Unclear | None:
    """Read ``message`` as 帮我问问 + names + question. None when it does not start that way (an ordinary message to
    the assistant). ``known``: the names of the twins that can be asked, each with the twins that go by it; ``own``:
    the names of the person's own twins, who are not asked."""
    cue = CUE.match(message)
    if cue is None:
        return None
    rest = message[cue.end() :]
    # Said with a colon, what comes before it is whom to ask and all of it must be names; said without, the names are
    # read from the front for as long as there are any.
    colon = _COLON.search(rest)
    address, spoken = (
        (rest[: colon.start()], rest[colon.end() :]) if colon and colon.start() <= ADDRESS_CHARS else (rest, "")
    )
    names: list[str] = []
    by_length = sorted(known, key=lambda name: (-len(name), name))
    while address:
        found = next((name for name in by_length if address.startswith(name)), None)
        if found is None:
            break
        if found not in names:
            names.append(found)
        address = _BETWEEN.sub("", address[len(found) :])
    if names and spoken:
        # What is left of the address after the names is someone who cannot be asked.
        left = _AFTER.sub("", address, count=1).strip()
        if left:
            return Unclear(f"团队里没有找到「{left}」，或者他的分身还没有开放给同事问。")
        rest = spoken
    else:
        rest = address
    if not names:
        token = _TOKEN.match(rest)
        if token is None:
            return Unclear("要问谁？说出同事的名字，比如“帮我问问王屿：……”。")
        if token.group(0) in own:
            return Unclear("这是你自己的分身，不用代问。")
        if not (colon and colon.start() <= ADDRESS_CHARS) and not _name_like(token.group(0)):
            # 帮我问一下，下周的会几点开？ asks the assistant something: what follows is no name of anyone.
            return None
        return Unclear(f"团队里没有找到「{token.group(0)}」，或者他的分身还没有开放给同事问。")
    if len(names) > MAX_DELEGATES:
        return Unclear(f"一次最多问 {MAX_DELEGATES} 位同事，你说了 {len(names)} 位。")
    clashes = [name for name in names if len(known[name]) > 1]
    if clashes:
        return Unclear(f"团队里不止一位叫「{clashes[0]}」，没有问出去。")
    question = _AFTER.sub("", rest, count=1).strip()
    if len(question) < MIN_QUESTION_CHARS:
        return Unclear(f"要问{'、'.join(names)}什么？把问题也说出来。")
    return Asked(tuple(names), question)


def asked_text(names: Sequence[str]) -> str:
    """What the assistant says once it has put the question: in the person's name, with the answers to read."""
    return f"已用你的名义问了{'、'.join(names)}，本人看得到。"


def mentions(answer: str, others: Mapping[str, str]) -> list[tuple[str, str]]:
    """The colleagues an answer sends the asker to (问沈从, 找陈一…): ``others`` maps a name to the twin it is; each
    found once, in the order they come. The assistant offers to ask them too, but only the person decides."""
    found: list[tuple[int, str, str]] = []
    for name, persona_id in others.items():
        hit = re.search(f"{_SEND_TO}{re.escape(name)}", answer)
        if hit is not None:
            found.append((hit.start(), name, persona_id))
    return [(name, persona_id) for _, name, persona_id in sorted(found)]


def target_state(
    reply: Mapping[str, Any] | None, handoff_status: str | None, skipped: bool, owner_replied: bool
) -> TargetState:
    """How one colleague's twin's card stands. ``reply``: its answer's metadata; ``handoff_status``: the state of the
    handoff the person made of it, if they did; ``skipped``: they said 先不用; ``owner_replied``: the colleague wrote
    back into the conversation."""
    if owner_replied:
        return "replied"
    if handoff_status is not None:
        return "replied" if handoff_status in ("replied", "accepted", "declined") else "handed"
    if reply is not None and reply.get("owner_part") not in (None, "none"):
        return "skipped" if skipped else "needs_owner"
    return "answered"
