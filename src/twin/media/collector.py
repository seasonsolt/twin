"""Version contract for the collector: what turns a recording into text attributed to people.

It has three layers, versioned apart because running each again costs so differently:

- ``asr``: the transcription service (asr-funasr's version and pipeline), which says who spoke when and what. A new
  one means transcribing again on the GPU, so the owner decides when; the library only says which recordings could
  be (``Library.recollectable``). Each transcript records the service that made it (``Transcript.asr``); one made
  before services said so is unknown (``None``), which is older than any known one. A service that only changed how
  precisely it computes, not who spoke when, counts as the one before it (``SAME_COLLECTION``): its transcripts
  differ in a few words, too little to transcribe a library again for.
- ``attribution``: the rules by which ``Team.classify`` gives a speaker to someone by voice alone. Automatic
  decisions record the version that made them (``attributions.version``); one made under other rules is decided
  again at start-up from the voice samples already there, in seconds.
- ``cleanup``: the rules by which ``Reviews.settle`` leaves suspect stretches of a confirmed speaker out of their twin.
  Automatic exclusions record their version (``segment_fixes.version``) and are judged again the same way.

Decisions of the owner carry no version: rules never undo what a person decided. Rows written before versions were
recorded have none and count as the first version of their layer, the rules that made them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Bump when ``Team.classify`` would decide speakers differently: every automatic decision is then made again.
# v3: voice samples left on older transcripts moved to their current speakers or retired (``recollect.settle_samples``).
ATTRIBUTION_VERSION = "attribution-v3"
# Bump when ``Reviews.settle`` would leave other stretches out: every automatic exclusion is then judged again.
CLEANUP_VERSION = "cleanup-v1"
# What rows without a recorded version were made by.
LEGACY_ATTRIBUTION = "attribution-v1"
LEGACY_CLEANUP = "cleanup-v1"

Scope = Literal["none", "cleanup", "attribution", "asr"]

# A transcription service → the earlier one it collects like. 1.5.4 runs FireRed in BF16 with incremental decoding:
# diarization, separation and voiceprints are 1.4.1's, and a few boundary words differ (docs/ASR_EVAL.md).
SAME_COLLECTION = {"1.5.4/overlap": "1.4.1/overlap", "1.5.4/classic": "1.4.1/classic"}


@dataclass(frozen=True)
class CollectorVersion:
    # ``<asr-funasr version>/<pipeline>``, e.g. "1.4.1/overlap"; None when the service did not say.
    asr: str | None
    attribution: str
    cleanup: str


def asr_version(version: object, pipeline: object) -> str | None:
    """The asr layer of a transcription service that reported ``version`` and ``pipeline``; None without a version."""
    if not isinstance(version, str) or not version.strip():
        return None
    if isinstance(pipeline, str) and pipeline.strip():
        return f"{version.strip()}/{pipeline.strip()}"
    return version.strip()


def collects_like(asr: str | None) -> str | None:
    """The earliest service ``asr`` collects like (``SAME_COLLECTION``), itself when none."""
    while asr in SAME_COLLECTION:
        asr = SAME_COLLECTION[asr]
    return asr


def recollect_scope(old: CollectorVersion, new: CollectorVersion) -> Scope:
    """The deepest layer that must run again for something collected by ``old`` to be as ``new`` would collect it:
    a layer run again runs every layer after it too. An unknown service is older than a known one; with the current
    service unknown nothing says the transcript is stale."""
    if new.asr is not None and collects_like(old.asr) != collects_like(new.asr):
        return "asr"
    if old.attribution != new.attribution:
        return "attribution"
    if old.cleanup != new.cleanup:
        return "cleanup"
    return "none"
