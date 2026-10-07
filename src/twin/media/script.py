"""Pure presentation conversion without generation or citation inference."""

from __future__ import annotations

from .schema import MediaScript, PresentableAnswer, Segment
from .speech_text import split_speech, strip_markdown

_ENDINGS = frozenset("。！？!?….\r\n")
_QUOTES = {"「": "」", "“": "”"}
_CLOSING_QUOTES = frozenset("」”\"'")


def _terminal_period(text: str, index: int) -> bool:
    before = text[index - 1] if index else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    if before.isdigit() and after.isdigit():
        return False
    return not after or after.isspace() or after in _CLOSING_QUOTES


def split_sentences(text: str) -> list[str]:
    """Keep punctuation clusters and quoted text intact, including decimal and version periods."""
    pieces: list[str] = []
    quotes: list[str] = []
    start = 0
    boundary = False
    for index, char in enumerate(text):
        if boundary and char not in _ENDINGS and char not in _CLOSING_QUOTES:
            if piece := text[start:index].strip():
                pieces.append(piece)
            start = index
            boundary = False
        if char in _QUOTES:
            quotes.append(_QUOTES[char])
        elif quotes and char == quotes[-1]:
            quotes.pop()
        elif not quotes and char in _ENDINGS and (char != "." or _terminal_period(text, index)):
            boundary = True
    if piece := text[start:].strip():
        pieces.append(piece)
    return pieces


def speech_script(script: MediaScript) -> MediaScript:
    """Rechunk only audio scripts; presentation and video keep their sentence layout."""
    text = "\n".join(segment.text for segment in script.segments if segment.kind == "speech")
    return script.model_copy(
        update={"segments": [Segment(index=i, kind="speech", text=piece) for i, piece in enumerate(split_speech(text))]}
    )


def _segments(text: str) -> list[Segment]:
    return [Segment(index=i, kind="speech", text=s) for i, s in enumerate(split_sentences(strip_markdown(text)))]


def script_from_presentable(p: PresentableAnswer, persona_name: str) -> MediaScript:
    """Present only the stable boundary contract without consulting upstream runtime types."""
    return MediaScript(
        source_kind=p.source_kind,
        source_fingerprint=p.source_fingerprint,
        persona_name=persona_name,
        as_of=p.as_of,
        confidence=p.confidence,
        abstain=p.abstain,
        segments=_segments(p.text),
        citations=list(p.citations),
    )
