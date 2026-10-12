"""Version contract for the persona memory kernel."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

PROMPT_VERSION = "persona-v4"
TAXONOMY_VERSION = "v1"

# Content fingerprints of each released version. Changing the extraction prompts or the taxonomy without bumping
# the version would leave every existing store on stale extractions with no rebuild, so tests pin these: a change
# must bump PROMPT_VERSION / TAXONOMY_VERSION and add the new fingerprint below.
PROMPT_FINGERPRINTS = {"persona-v4": "a04b10cde3156c9131d60d3faf62113dc9120dc620f6647d5874265e85424953"}
TAXONOMY_FINGERPRINTS = {"v1": "709b4a45adf588753f44a56e67780c93d76cb5f41f48caf89e991c20c77c5624"}


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


def content_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
