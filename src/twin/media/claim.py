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

from PIL import Image, ImageOps
from pydantic import BaseModel, Field

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
    speaker: str | None = None
    confirmed: bool = False
    suggested: str | None = None
    automatic: bool = False
    revision: str = Field(default_factory=lambda: uuid.uuid4().hex)
    voices: list[Candidate] = Field(default_factory=list)
    portraits: list[Candidate] = Field(default_factory=list)
    candidate_error: str | None = None

    def save(self, folder: Path) -> None:
        AssetStore.write(folder / "analysis.json", self.model_dump_json().encode())

    @classmethod
    def load(cls, folder: Path) -> Analysis:
        return cls.model_validate_json((folder / "analysis.json").read_bytes())

    def lines(self, name: str) -> list[tuple[str, str, bool]]:
        others = {s.id: f"其他人{i + 1}" for i, s in enumerate(s for s in self.speakers if s.id != self.speaker)}
        return [
            (
                name if s.speaker == self.speaker else others[s.speaker],
                f"[{timestamp(s.start)}] {' '.join(s.text.split())}",
                s.speaker == self.speaker,
            )
            for s in self.segments
            if s.text.strip()
        ]


def analyse(segments: list[Segment], speakers: list[Speaker], has_reference: bool) -> Analysis:
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
        )
        for sid in ids
    ]
    ranked = sorted((s for s in speakers if s.similarity is not None), key=lambda s: s.similarity or 0, reverse=True)
    suggested = ranked[0].id if has_reference and ranked else None
    chosen = speakers[0].id if len(speakers) == 1 else None
    if chosen is None and suggested:
        best = ranked[0].similarity or 0
        runner = (ranked[1].similarity or 0) if len(ranked) > 1 else 0
        if len(ranked) == len(speakers) and best >= 0.6 and best - runner >= 0.1 - 1e-9:
            chosen = suggested
    return Analysis(
        segments=segments,
        speakers=speakers,
        speaker=chosen,
        confirmed=chosen is not None,
        suggested=suggested,
        automatic=chosen is not None,
    )


def intervals(analysis: Analysis, speaker: str) -> list[tuple[float, float]]:
    # Never include overlap with another speaker, even inside a merged run.
    others = [(s.start, s.end) for s in analysis.segments if s.speaker != speaker]
    runs: list[tuple[float, float]] = []
    for s in sorted((s for s in analysis.segments if s.speaker == speaker), key=lambda s: s.start):
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
    if analysis.speaker is None:
        return []
    runs = intervals(analysis, analysis.speaker)
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


def voice_candidates(analysis: Analysis, folder: Path) -> list[Candidate]:
    candidates = []
    for i, (start, end) in enumerate(voice_windows(analysis, folder / "audio.wav")):
        cid = f"{analysis.revision}-voice-{i}"
        cut(folder / "audio.wav", folder / f"{cid}.wav", start, end)
        candidates.append(Candidate(id=cid, file=f"{cid}.wav", start=start, end=end))
    return candidates


def sample_windows(analysis: Analysis, speaker: str) -> list[tuple[float, float]]:
    runs = sorted(intervals(analysis, speaker), key=lambda p: p[1] - p[0], reverse=True)
    windows = []
    for start, end in runs:
        count = 3 if end - start >= 5 else 1
        for i in range(count):
            offset = (end - start - 5) * i / max(count - 1, 1) if end - start > 5 else 0
            windows.append((start + offset, min(start + offset + 5, end)))
        if len(windows) >= 3:
            break
    return windows[:3]


def vision_candidates(analysis: Analysis, video: Path, folder: Path, settings: VisionSettings) -> list[Candidate]:
    if not settings.command or analysis.speaker is None:
        return []
    with tempfile.TemporaryDirectory(dir=folder, prefix=".vision-") as temporary:
        out = Path(temporary).resolve()
        result = subprocess.run(
            ["bash", "-lc", settings.command],
            input=json.dumps(
                {
                    "video": str(video.resolve()),
                    "intervals": intervals(analysis, analysis.speaker),
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
