"""Version contract for the persona memory kernel."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

PROMPT_VERSION = "persona-v7"
TAXONOMY_VERSION = "v2"

# Content fingerprints of each released version. Changing the extraction prompts or the taxonomy without bumping
# the version would leave every existing store on stale extractions with no rebuild, so tests pin these: a change
# must bump PROMPT_VERSION / TAXONOMY_VERSION and add the new fingerprint below.
PROMPT_FINGERPRINTS = {
    "persona-v4": "a04b10cde3156c9131d60d3faf62113dc9120dc620f6647d5874265e85424953",
    "persona-v5": "cf0cdafbd3252d51755f38c7afbbf50c45d8ebb81b3e77cd5646b4f24b70f9c4",
    "persona-v6": "198573d74d889724d9198406ddda5b10c5b5a858271f1535fc64b48c57d26780",
    "persona-v7": "f06ded265abed0b6defd43bead329e472772651d8820d91a8d74c2ebcc6fe5a0",
}
TAXONOMY_FINGERPRINTS = {
    "v1": "709b4a45adf588753f44a56e67780c93d76cb5f41f48caf89e991c20c77c5624",
    "v2": "953fbda71005252b1746adb953d5693bf9480a38d383f4ee7e40373a3f48563f",
}


_FACETS_V1 = (
    *("1.1", "1.2", "1.3", "1.4"),
    *("2.1", "2.2", "2.3", "2.4"),
    *("3.1", "3.2", "3.3", "3.4", "3.5", "3.6"),
    *("4.1", "4.2", "4.3", "4.4"),
    *("5.1", "5.2", "5.3"),
    *("6.1", "6.2", "6.3", "6.4", "6.5"),
    *("7.1", "7.2", "7.3", "7.4", "7.5"),
    *("8.1", "8.2", "8.3"),
    *("9.1", "9.2", "9.3", "9.4", "9.5"),
)
# Facet ids of each released taxonomy, oldest first. A store records the taxonomy its facet ids belong to and is moved
# forward on open by TAXONOMY_MIGRATIONS, so stored items never carry an id the running taxonomy does not know.
TAXONOMY_FACET_IDS: dict[str, tuple[str, ...]] = {
    "v1": _FACETS_V1,
    "v2": _FACETS_V1,
}
# For each version after the first: where the previous version's facet ids go. An id that stays need not be listed.
# A tuple names its new facets: the first holds the old items until the rebuild re-merges them, and the others inherit
# the person's reviews of those items at that re-merge. An empty tuple removes the facet and its items.
TAXONOMY_MIGRATIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "v2": {},
}


def taxonomy_plan(old: str, new: str) -> dict[str, tuple[str, ...]] | None:
    """Where each facet id of taxonomy ``old`` ends up in ``new``, listing only the ids that move or go; None when
    either version is unknown here or ``old`` is not older (a store written by a newer twin is left as it is)."""
    versions = list(TAXONOMY_FACET_IDS)
    if old not in versions or new not in versions or versions.index(old) > versions.index(new):
        return None
    where: dict[str, tuple[str, ...]] = {facet_id: (facet_id,) for facet_id in TAXONOMY_FACET_IDS[old]}
    for version in versions[versions.index(old) + 1 : versions.index(new) + 1]:
        step = TAXONOMY_MIGRATIONS[version]
        where = {
            facet_id: tuple(dict.fromkeys(t for current in targets for t in step.get(current, (current,))))
            for facet_id, targets in where.items()
        }
    return {facet_id: targets for facet_id, targets in where.items() if targets != (facet_id,)}


@dataclass(frozen=True)
class KernelVersion:
    schema: int
    prompt: str
    taxonomy: str


KERNEL = KernelVersion(schema=4, prompt=PROMPT_VERSION, taxonomy=TAXONOMY_VERSION)
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
