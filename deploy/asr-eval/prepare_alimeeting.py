# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=1.26"]
# ///
"""把解压后的 AliMeeting Eval/Test（OpenSLR SLR119）转成分层 ASR 评测的清单。

    uv run deploy/asr-eval/prepare_alimeeting.py <解压目录>/Eval_Ali --out <仓库外目录>

输入目录含 `*_Ali_far/{audio_dir,textgrid_dir}` 和 `*_Ali_near/audio_dir`。远场取 8 通道阵列的第 0 通道，最接近
手机或笔记本单个麦克风的录音。输出：

- `sessions/<场次>.wav` 与 `sessions/<场次>.json`（参考 `{"segments": [{start, end, speaker, text}]}`），
  以及 `sessions.jsonl`：每场一行 `{id, audio, duration, reference, references}`，`references` 为
  `{说话人: 参考声音路径}`；供 `twin eval-asr-session`（L2/L3/L5）使用。
- `clips/far/*.wav` + `manifest-far.jsonl`、`clips/near/*.wav` + `manifest-near.jsonl`：不与他人重叠的单句，
  `group` 为场次，格式与 eval-asr 清单相同（L1）。
- `voices/<说话人>.wav`：取自该说话人另一场会议的近场录音、约 10 秒不与他人重叠的语音，模拟用户在 twin 里
  录的本人参考声音；只参加一场的说话人没有参考声音，也不作为「本人」评测。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

RATE = 16000
VOICE_SECONDS = 10.0
VOICE_MAX_SECONDS = 20.0
MIN_CLIP_SECONDS = 0.3
# Transcription marks in AliMeeting TextGrids (see the M2MeT recipe's text normalization), not spoken words.
_MARKS = re.compile(r"<[^<>]*>|\((?:~|/?[A-Za-z]+)\)|[`&]")
_LONG = re.compile(r'xmin\s*=\s*([-\d.eE]+)\s*xmax\s*=\s*([-\d.eE]+)\s*text\s*=\s*"((?:[^"]|"")*)"', re.MULTILINE)
_TIER = re.compile(r'class\s*=\s*"IntervalTier"\s*name\s*=\s*"((?:[^"]|"")*)"')


@dataclass(frozen=True)
class Turn:
    start: float
    end: float
    speaker: str
    text: str


def clean_text(text: str) -> str:
    return " ".join(_MARKS.sub(" ", text).split())


def read_textgrid(path: Path) -> list[Turn]:
    """Praat long-format TextGrid: one IntervalTier per speaker, intervals with text; blank intervals dropped."""
    raw = path.read_bytes()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    content = raw.decode(encoding)
    starts = [(m.start(), m.group(1).replace('""', '"')) for m in _TIER.finditer(content)]
    if not starts:
        raise ValueError(f"{path.name} 不是长格式 IntervalTier TextGrid")
    turns: list[Turn] = []
    for k, (offset, speaker) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(content)
        for m in _LONG.finditer(content, offset, end):
            text = clean_text(m.group(3).replace('""', '"'))
            if text:
                turns.append(Turn(round(float(m.group(1)), 3), round(float(m.group(2)), 3), speaker.strip(), text))
    return sorted(turns, key=lambda t: (t.start, t.end, t.speaker))


def isolated(turns: list[Turn]) -> list[Turn]:
    """Turns that overlap no other speaker's turn."""
    return [t for t in turns if not any(o.speaker != t.speaker and o.start < t.end and t.start < o.end for o in turns)]


def read_channel(path: Path, channel: int = 0) -> np.ndarray:
    """One channel of a 16-bit PCM WAV at 16 kHz, read a minute at a time so an 8-channel 30-minute file never sits
    in memory whole."""
    parts: list[np.ndarray] = []
    try:
        with wave.open(str(path), "rb") as source:
            rate, width, channels = source.getframerate(), source.getsampwidth(), source.getnchannels()
            if rate != RATE or width != 2:
                raise ValueError(f"{path.name} 为 {rate} Hz、{8 * width} 位，应为 {RATE} Hz、16 位")
            if channel >= channels:
                raise ValueError(f"{path.name} 只有 {channels} 个通道")
            while block := source.readframes(RATE * 60):
                parts.append(np.frombuffer(block, dtype="<i2").reshape(-1, channels)[:, channel].copy())
    except (wave.Error, EOFError) as error:
        raise ValueError(f"{path.name} 不是 16 位 PCM WAV：{error}") from None
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)


def write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.astype(np.int16).tobytes())


def cut(samples: np.ndarray, start: float, end: float) -> np.ndarray:
    return samples[max(0, round(start * RATE)) : max(0, round(end * RATE))]


def voice_sample(samples: np.ndarray, turns: list[Turn], speaker: str) -> np.ndarray | None:
    """About VOICE_SECONDS of the speaker's isolated speech, longest turns first, capped at VOICE_MAX_SECONDS."""
    own = sorted((t for t in isolated(turns) if t.speaker == speaker), key=lambda t: (t.start - t.end, t.start))
    pieces: list[np.ndarray] = []
    total = 0.0
    for turn in own:
        if total >= VOICE_SECONDS:
            break
        length = min(turn.end - turn.start, VOICE_MAX_SECONDS - total)
        pieces.append(cut(samples, turn.start, turn.start + length))
        total += length
    return np.concatenate(pieces) if total >= VOICE_SECONDS / 2 else None


def find_split(root: Path) -> tuple[Path, Path | None]:
    far = next((p for p in sorted(root.glob("*_Ali_far")) if p.is_dir()), None)
    near = next((p for p in sorted(root.glob("*_Ali_near")) if p.is_dir()), None)
    if far is None:
        raise ValueError(f"{root} 下没有 *_Ali_far 目录")
    return far, near


def session_audio(far: Path, session: str) -> Path:
    found = sorted((far / "audio_dir").glob(f"{session}_*.wav")) or sorted((far / "audio_dir").glob(f"{session}.wav"))
    if not found:
        raise ValueError(f"缺少场次 {session} 的远场录音")
    return found[0]


def near_audio(near: Path | None, session: str, speaker: str) -> Path | None:
    if near is None:
        return None
    path = near / "audio_dir" / f"{session}_N_{speaker}.wav"
    return path if path.is_file() else None


def prepare(root: Path, out: Path) -> dict[str, int]:
    far, near = find_split(root)
    grids = sorted((far / "textgrid_dir").glob("*.TextGrid"))
    if not grids:
        raise ValueError(f"{far / 'textgrid_dir'} 下没有 TextGrid")
    sessions = {g.stem: read_textgrid(g) for g in grids}
    lines: dict[str, list[str]] = {"far": [], "near": [], "sessions": []}
    voices: dict[str, Path] = {}
    attended: dict[str, list[str]] = {}
    for session, turns in sessions.items():
        for speaker in sorted({t.speaker for t in turns}):
            attended.setdefault(speaker, []).append(session)
    # Reference voice: the last session (sorted) the speaker attends; that session is not scored for them.
    for speaker, places in sorted(attended.items()):
        if len(places) < 2:
            continue
        source = places[-1]
        audio = near_audio(near, source, speaker)
        if audio is None:
            continue
        sample = voice_sample(read_channel(audio), sessions[source], speaker)
        if sample is not None:
            voices[speaker] = out / "voices" / f"{speaker}.wav"
            write_wav(voices[speaker], sample)
    voice_source = {speaker: attended[speaker][-1] for speaker in voices}
    for session, turns in sessions.items():
        samples = read_channel(session_audio(far, session))
        write_wav(out / "sessions" / f"{session}.wav", samples)
        reference = {"segments": [t.__dict__ for t in turns]}
        (out / "sessions" / f"{session}.json").write_text(json.dumps(reference, ensure_ascii=False), encoding="utf-8")
        references = {
            speaker: f"voices/{speaker}.wav"
            for speaker in sorted({t.speaker for t in turns})
            if speaker in voices and voice_source[speaker] != session
        }
        row = {
            "id": session,
            "audio": f"sessions/{session}.wav",
            "duration": round(len(samples) / RATE, 3),
            "reference": f"sessions/{session}.json",
            "references": references,
        }
        lines["sessions"].append(json.dumps(row, ensure_ascii=False))
        near_cache: dict[str, np.ndarray | None] = {}
        for k, turn in enumerate(isolated(turns)):
            if turn.end - turn.start < MIN_CLIP_SECONDS:
                continue
            clip_id = f"{session}-{k:04d}"
            base = {"text": turn.text, "duration": round(turn.end - turn.start, 3), "group": session}
            write_wav(out / "clips" / "far" / f"{clip_id}.wav", cut(samples, turn.start, turn.end))
            lines["far"].append(
                json.dumps({"id": clip_id, "audio": f"clips/far/{clip_id}.wav", **base}, ensure_ascii=False)
            )
            if turn.speaker not in near_cache:
                path = near_audio(near, session, turn.speaker)
                near_cache[turn.speaker] = read_channel(path) if path else None
            own = near_cache[turn.speaker]
            if own is not None:
                write_wav(out / "clips" / "near" / f"{clip_id}.wav", cut(own, turn.start, turn.end))
                lines["near"].append(
                    json.dumps({"id": clip_id, "audio": f"clips/near/{clip_id}.wav", **base}, ensure_ascii=False)
                )
    for name, file in (("far", "manifest-far.jsonl"), ("near", "manifest-near.jsonl"), ("sessions", "sessions.jsonl")):
        (out / file).write_text("".join(line + "\n" for line in lines[name]), encoding="utf-8")
    return {
        "sessions": len(lines["sessions"]),
        "far_clips": len(lines["far"]),
        "near_clips": len(lines["near"]),
        "voices": len(voices),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("root", type=Path, help="解压后的 Eval_Ali 或 Test_Ali 目录")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        counts = prepare(args.root, args.out)
    except ValueError as error:
        sys.exit(str(error))
    print(
        f"{counts['sessions']} 场，远场片段 {counts['far_clips']} 条，近场片段 {counts['near_clips']} 条，"
        f"参考声音 {counts['voices']} 人 → {args.out}"
    )


if __name__ == "__main__":
    main()
