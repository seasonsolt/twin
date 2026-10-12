"""Version contract for the persona memory kernel."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

PROMPT_VERSION = "persona-v4"
TAXONOMY_VERSION = "v1"


@dataclass(frozen=True)
class KernelVersion:
    schema: int
    prompt: str
    taxonomy: str


KERNEL = KernelVersion(schema=1, prompt=PROMPT_VERSION, taxonomy=TAXONOMY_VERSION)
LEGACY_KERNEL = KernelVersion(schema=1, prompt="persona-v4", taxonomy="v1")


def kernel_json(k: KernelVersion) -> str:
    return json.dumps(
        {"schema": k.schema, "prompt": k.prompt, "taxonomy": k.taxonomy}, sort_keys=True, separators=(",", ":")
    )


def rebuild_scope(old: KernelVersion | None, new: KernelVersion) -> Literal["none", "merge", "full"]:
    if old is None:
        old = LEGACY_KERNEL
    if old.prompt != new.prompt:
        return "full"
    if old.taxonomy != new.taxonomy:
        return "merge"
    return "none"
