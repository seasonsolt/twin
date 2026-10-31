"""合成同意 (docs/PRODUCT_PERSONA_AGENT.md P3.3): the person's own voice or portrait is used to synthesize speech or
video only once they agreed to it, for that very recording or photo.

Each agreement and each withdrawal is a line of ``p_media_consent`` (append-only, like the will's history): when, which
kind, the material's content key (its SHA-256, so a new recording or photo needs agreeing to again) and the words the
person agreed to (``TEXTS``), as they were shown. The latest line for a material decides. Without it, speech uses the
preset voice and video the preset figure; recognising the person's voice in recordings needs none.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

from .store import PersonaStore

Kind = Literal["voice", "portrait"]
# What the person agrees to, shown with the box they tick and kept with their agreement.
TEXTS: dict[Kind, str] = {
    "voice": "我同意用这段我自己的声音合成朗读和视频里的话。每段合成的声音开头会说“以下为 AI 合成”，文件里也写明是 AI "
    "合成。我可以随时撤回。",
    "portrait": "我同意用这张我自己的照片生成会说话的视频。视频画面角上一直标着“AI 合成”，导出的文件里也有。"
    "我可以随时撤回。",
}


def consented(store: PersonaStore, kind: Kind, content_key: str | None) -> bool:
    """Whether the person's latest word on this material of ``kind`` is that they agree; False for no material."""
    if not content_key:
        return False
    said = [granted for _, k, key, granted, _ in store.consents() if k == kind and key == content_key]
    return bool(said) and said[-1]


def agreed_to(db_path: Path, kind: Kind, content_key: str) -> bool:
    """``consented``, read from the twin's database at ``db_path`` (for the media layer, which keeps no store)."""
    with PersonaStore(db_path) as store:
        return consented(store, kind, content_key)


def give(store: PersonaStore, kind: Kind, content_key: str, now: dt.datetime | None = None) -> None:
    """The person agrees, with ``TEXTS[kind]`` as their words."""
    at = (now or dt.datetime.now(dt.UTC)).isoformat(timespec="seconds")
    store.add_consent(at, kind, content_key, True, TEXTS[kind])


def withdraw(store: PersonaStore, kind: Kind, content_key: str, now: dt.datetime | None = None) -> None:
    """The person withdraws; their earlier agreement stays on record, no longer in force."""
    at = (now or dt.datetime.now(dt.UTC)).isoformat(timespec="seconds")
    store.add_consent(at, kind, content_key, False, "撤回")
