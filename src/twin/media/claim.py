"""Speaker decisions and locally prepared reference candidates for a recording."""

from __future__ import annotations

import array
import json
import math
import statistics
import subprocess
import tempfile
import uuid
import wave
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from pydantic import BaseModel, Field, computed_field, model_validator

from ..assets import AssetStore
from ..config import VisionSettings
from .ingest import Segment, Speaker, timestamp


class Candidate(BaseModel):
    id: str
    file: str
    start: float = Field(default=0, ge=0, allow_inf_nan=False)
    end: float = Field(default=0, ge=0, allow_inf_nan=False)
    score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    face_box: tuple[float, float, float, float] | None = None


class Analysis(BaseModel):
    segments: list[Segment]
    speakers: list[Speaker]
    claimed: list[str] = Field(default_factory=list)
    diarized: bool = True
    also_suggested: list[str] = Field(default_factory=list)
    confirmed: bool = False
    suggested: str | None = None
    automatic: bool = False
    revision: str = Field(default_factory=lambda: uuid.uuid4().hex)
    voices: list[Candidate] = Field(default_factory=list)
    portraits: list[Candidate] = Field(default_factory=list)
    candidate_error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_speaker(cls, data: Any) -> Any:
        if isinstance(data, dict) and "claimed" not in data:
            data = {**data, "claimed": [data["speaker"]] if data.get("speaker") is not None else []}
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def speaker(self) -> str | None:
        return self.claimed[0] if self.claimed else None

    def save(self, folder: Path) -> None:
        AssetStore.write(folder / "analysis.json", self.model_dump_json().encode())

    @classmethod
    def load(cls, folder: Path) -> Analysis:
        return cls.model_validate_json((folder / "analysis.json").read_bytes())

    def lines(self, name: str) -> list[tuple[str, str, bool]]:
        others = {s.id: f"其他人{i + 1}" for i, s in enumerate(s for s in self.speakers if s.id not in self.claimed)}
        return [
            (
                name if s.speaker in self.claimed else others[s.speaker],
                f"[{timestamp(s.start)}] {' '.join(s.text.split())}",
                s.speaker in self.claimed,
            )
            for s in self.segments
            if s.text.strip()
        ]


# Cosine similarity between the person's reference voice and a speaker cluster, measured with twin eval-asr-session on
# AliMeeting Eval + Test (far-field meetings, headset reference voices). The best cluster is claimed from AUTO_CLAIM:
# people absent from the meeting never passed 0.44. Diarization often splits one person into several clusters, so
# further clusters are claimed too, but only from ALSO_CLAIM: small clusters of another person (overlapped speech)
# reached 0.53. Unclaimed clusters from ALSO_SUGGEST are offered as "maybe you".
# A reference voice cut from a far-field meeting (docs/MEDIA.md) lifts everyone in the room: on AISHELL-4 the
# person's best cluster sat near 0.85 and other people in the room reached 0.66, so further clusters must also be
# within CLAIM_GAP of the best one, and suggestions within SUGGEST_GAP. Chosen on room R003, checked on R004; every
# split of the person on AliMeeting was within 0.2 and every suggestion that was them within 0.3 (docs/ASR_EVAL.md).
AUTO_CLAIM = 0.5
ALSO_CLAIM = 0.55
ALSO_SUGGEST = 0.45
CLAIM_GAP = 0.2
SUGGEST_GAP = 0.3


def analyse(segments: list[Segment], speakers: list[Speaker], has_reference: bool, diarized: bool = True) -> Analysis:
    if not any(s.text.strip() for s in segments):
        raise ValueError("没有识别到文字")
    metadata = {s.id: s for s in speakers}
    ids = list(dict.fromkeys(s.speaker for s in segments))
    speakers = [
        Speaker(
            id=sid,
            seconds=metadata[sid].seconds
            if sid in metadata
            else sum(s.end - s.start for s in segments if s.speaker == sid),
            similarity=metadata[sid].similarity if sid in metadata else None,
            embedding=metadata[sid].embedding if sid in metadata else None,
        )
        for sid in ids
    ]
    ranked = sorted((s for s in speakers if s.similarity is not None), key=lambda s: s.similarity or 0, reverse=True)
    suggested = ranked[0].id if diarized and has_reference and ranked else None
    best = (ranked[0].similarity or 0) if ranked else 0

    def near(speaker: Speaker, floor: float, gap: float) -> bool:
        return (speaker.similarity or 0) >= floor - 1e-9 and best - (speaker.similarity or 0) <= gap + 1e-9

    claimed: list[str] = []
    if diarized and len(speakers) == 1 and not has_reference:
        claimed = [speakers[0].id]
    elif suggested and len(ranked) == len(speakers) and best >= AUTO_CLAIM - 1e-9:
        claimed = [suggested] + [s.id for s in ranked[1:] if near(s, ALSO_CLAIM, CLAIM_GAP)]
    return Analysis(
        segments=segments,
        speakers=speakers,
        claimed=claimed,
        diarized=diarized,
        also_suggested=[
            s.id for s in ranked if s.id != suggested and s.id not in claimed and near(s, ALSO_SUGGEST, SUGGEST_GAP)
        ]
        if suggested
        else [],
        confirmed=bool(claimed),
        suggested=suggested,
        automatic=bool(claimed),
    )


def rescore(analysis: Analysis, reference: list[float]) -> Analysis | None:
    """Decide again with a new reference voice from the stored voiceprints, as `analyse` would have after transcribing.

    None when nothing changes, the person chose the speakers themselves, or a speaker has no voiceprint (transcribed
    before asr-funasr 1.3.0)."""
    if not analysis.diarized or (analysis.confirmed and not analysis.automatic):
        return None
    if any(s.embedding is None or len(s.embedding) != len(reference) for s in analysis.speakers):
        return None

    def similarity(embedding: list[float]) -> float:
        # Both are unit vectors, rounded like asr-funasr's own similarity.
        return round(min(1.0, max(0.0, sum(a * b for a, b in zip(embedding, reference, strict=True)))), 3)

    speakers = [s.model_copy(update={"similarity": similarity(s.embedding or [])}) for s in analysis.speakers]
    decided = analyse(analysis.segments, speakers, True)
    if (decided.claimed, decided.suggested, decided.also_suggested) == (
        analysis.claimed,
        analysis.suggested,
        analysis.also_suggested,
    ):
        return None
    return decided


def intervals(analysis: Analysis, speaker: str | None = None) -> list[tuple[float, float]]:
    claimed = {speaker} if speaker is not None else set(analysis.claimed)
    # Never include overlap with an unclaimed speaker, even inside a merged run.
    others = [(s.start, s.end) for s in analysis.segments if s.speaker not in claimed]
    runs: list[tuple[float, float]] = []
    for s in sorted((s for s in analysis.segments if s.speaker in claimed), key=lambda s: s.start):
        if runs and s.start - runs[-1][1] < 0.6 and not any(a < s.start and b > runs[-1][1] for a, b in others):
            runs[-1] = runs[-1][0], max(runs[-1][1], s.end)
        else:
            runs.append((s.start, s.end))
    for a, b in others:
        runs = (
            [(x, y) for start, end in runs for x, y in ((start, min(end, a)), (max(start, b), end)) if y > x]
            if b > a
            else runs
        )
    return runs


def voice_windows(analysis: Analysis, audio: Path | None = None) -> list[tuple[float, float]]:
    if not analysis.claimed:
        return []
    runs = intervals(analysis)
    duration = math.inf
    if audio:
        with wave.open(str(audio)) as wav:
            duration = wav.getnframes() / wav.getframerate()
    windows: list[tuple[float, float]] = []
    for start, end in runs:
        end = min(end, duration)
        # Trim edges a little where there is enough speech, away from speaker transitions.
        if end - start > 9:
            start, end = start + 0.2, end - 0.2
        while end - start >= 8:
            stop = min(start + 20, end)
            windows.append((start, stop))
            start = stop

    def rank(window: tuple[float, float]) -> tuple[float, float]:
        start, end = window
        quality = 0.0
        if audio:
            levels = []
            with wave.open(str(audio)) as wav:
                rate = wav.getframerate()
                wav.setpos(round(start * rate))
                for _ in range(int(end - start)):
                    samples = array.array("h", wav.readframes(rate))
                    if samples:
                        levels.append(math.sqrt(sum(n * n for n in samples) / len(samples)))
            if levels:
                mean = statistics.mean(levels)
                quality = mean / (1 + statistics.pstdev(levels) / max(mean, 1))
        return round(end - start, 1), quality

    return sorted(windows, key=rank, reverse=True)[:3]


def cut(audio: Path, output: Path, start: float, end: float) -> None:
    if end <= start:
        raise ValueError("音频片段为空")
    output.touch(mode=0o600)
    output.chmod(0o600)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-ss",
            str(start),
            "-i",
            str(audio),
            "-t",
            str(end - start),
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            "-map_metadata",
            "-1",
            str(output),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )


def voice_candidates(analysis: Analysis, folder: Path, audio: Path) -> list[Candidate]:
    """Cut the claimed speakers' voice candidates from ``audio``, the source's sound (see ``readable_wav``)."""
    candidates = []
    for i, (start, end) in enumerate(voice_windows(analysis, audio)):
        cid = f"{analysis.revision}-voice-{i}"
        cut(audio, folder / f"{cid}.wav", start, end)
        candidates.append(Candidate(id=cid, file=f"{cid}.wav", start=start, end=end))
    return candidates


def sample_path(folder: Path, window: tuple[float, float]) -> Path:
    """Where the listening sample of ``window`` is kept. It is named by its times alone: the same original cut at the
    same times is the same sound, so a sample outlives choosing who is who (a new revision) and even a
    transcription again."""
    start, end = window
    return folder / f"sample-{round(start * 1000)}-{round(end * 1000)}.wav"


def missing_samples(analysis: Analysis, folder: Path) -> bool:
    return any(
        not sample_path(folder, window).is_file()
        for speaker in analysis.speakers
        for window in sample_windows(analysis, speaker.id)
    )


def cut_samples(analysis: Analysis, folder: Path, audio: Path) -> None:
    """Cut every speaker's listening samples that are not there yet from ``audio``, so choosing who is who does not
    wait for the original to be decoded again. Each is written aside and renamed, so a sample on disk is whole."""
    for speaker in analysis.speakers:
        for window in sample_windows(analysis, speaker.id):
            path = sample_path(folder, window)
            if path.is_file():
                continue
            temporary = path.with_name(f".{path.stem}-{uuid.uuid4().hex}.wav")
            try:
                cut(audio, temporary, *window)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)


# How long one moment to hear a speaker at lasts: long enough to hold several sentences, not one.
SAMPLE_SECONDS = 20.0
# Pauses this short between a speaker's sentences, with nobody else speaking, still belong to one moment.
SAMPLE_GAP_SECONDS = 3.0


def sample_windows(analysis: Analysis, speaker: str) -> list[tuple[float, float]]:
    """Up to three moments to hear the speaker at, each at most ``SAMPLE_SECONDS`` long and none overlapping another.
    Sentences with only a short pause between them (and nobody else speaking) form one stretch, so a moment holds
    several sentences rather than one. Each of the three longest stretches gives one moment, so they are different
    parts of the meeting and a speaker who is really several people sounds like it. With fewer stretches, the longest
    ones are spread over with further windows spaced evenly through them, not taken one right after another."""
    others = [(s.start, s.end) for s in analysis.segments if s.speaker != speaker]
    stretches: list[tuple[float, float]] = []
    for start, end in intervals(analysis, speaker):
        last = stretches[-1] if stretches else None
        if last and start - last[1] < SAMPLE_GAP_SECONDS and not any(a < start and b > last[1] for a, b in others):
            stretches[-1] = last[0], end
        else:
            stretches.append((start, end))
    stretches = sorted(stretches, key=lambda p: p[1] - p[0], reverse=True)[:3]
    counts = [1] * len(stretches)
    while sum(counts) < 3 and stretches:
        # Give the next window to the stretch with the most room per window, if a whole window still fits.
        room = [(end - start) / (n + 1) for (start, end), n in zip(stretches, counts, strict=True)]
        best = max(range(len(room)), key=room.__getitem__)
        if room[best] < SAMPLE_SECONDS:
            break
        counts[best] += 1
    windows: list[tuple[float, float]] = []
    for (start, end), n in zip(stretches, counts, strict=True):
        for i in range(n):
            offset = (end - start - SAMPLE_SECONDS) * i / (n - 1) if n > 1 else 0
            begin = start + offset
            windows.append((begin, min(begin + SAMPLE_SECONDS, end)))
    return windows


def vision_candidates(analysis: Analysis, video: Path, folder: Path, settings: VisionSettings) -> list[Candidate]:
    if not settings.command or not analysis.claimed:
        return []
    with tempfile.TemporaryDirectory(dir=folder, prefix=".vision-") as temporary:
        out = Path(temporary).resolve()
        result = subprocess.run(
            ["bash", "-lc", settings.command],
            input=json.dumps(
                {
                    "video": str(video.resolve()),
                    "intervals": intervals(analysis),
                    "out_dir": str(out),
                    "max_candidates": 6,
                }
            ),
            text=True,
            capture_output=True,
            check=True,
            timeout=1800,
        )
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        if payload.get("ok") is not True or not isinstance(payload.get("candidates"), list):
            raise ValueError("形象提取失败")
        validated: list[tuple[Path, Candidate]] = []
        for item in payload["candidates"]:
            path = Path(item["image"])
            # Check lexical containment and every component before following any link.
            if not path.is_absolute() or ".." in path.parts or not path.is_relative_to(out):
                raise ValueError("形象候选路径无效")
            if (
                any(p.is_symlink() for p in (path, *path.parents))
                or not path.is_file()
                or not path.resolve().is_relative_to(out)
            ):
                raise ValueError("形象候选路径无效")
            candidate = Candidate(
                id=f"{analysis.revision}-portrait-{len(validated)}",
                file="",
                start=item["time"],
                score=item["score"],
                face_box=item.get("face_box"),
            )
            if candidate.face_box:
                x, y, w, h = candidate.face_box
                if (
                    not all(math.isfinite(n) and 0 <= n <= 1 for n in candidate.face_box)
                    or w <= 0
                    or h <= 0
                    or x + w > 1
                    or y + h > 1
                ):
                    raise ValueError("人脸范围无效")
            validated.append((path, candidate))
        candidates = []
        for path, candidate in validated[:6]:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            clean = Image.new("RGB", image.size)
            clean.paste(image)
            candidate.file = f"{candidate.id}.png"
            output = folder / candidate.file
            output.touch(mode=0o600)
            clean.save(output, "PNG")
            output.chmod(0o600)
            candidates.append(candidate)
        return candidates


def face_crop(candidate: Candidate, path: Path) -> dict[str, str]:
    if candidate.face_box is None:
        return {}
    with Image.open(path) as image:
        width, height = image.size
    x, y, w, h = candidate.face_box
    crop_w, crop_h = min(width, height * 3 / 4), min(height, width * 4 / 3)
    left = max(0, min(width - crop_w, (x + w / 2) * width - crop_w / 2))
    top = max(0, min(height - crop_h, (y + h / 2) * height - crop_h / 2))
    return dict(
        zip(("x", "y", "w", "h"), map(str, (left / width, top / height, crop_w / width, crop_h / height)), strict=True)
    )
