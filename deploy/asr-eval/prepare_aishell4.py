# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=1.26", "soundfile>=0.12"]
# ///
"""把解压后的 AISHELL-4 测试集（OpenSLR SLR111，test.tar.gz）转成 `twin eval-asr-session` 的场次清单。

    uv run deploy/asr-eval/prepare_aishell4.py <解压目录>/test --out <仓库外目录>

输入目录含 `wav/<场次>.flac`（8 通道圆形阵列，16 kHz）和 `TextGrid/<场次>.TextGrid`（每人一层，层名形如
`006-M`）。远场取第 0 通道，和 AliMeeting 的做法一样。输出：

- `sessions/<场次>.wav` 与 `sessions/<场次>.json`（参考 `{"segments": [{start, end, speaker, text}]}`），以及
  `sessions.jsonl`：每场一行 `{id, audio, duration, reference, references, voice_from, group}`。
- `voices/<说话人>.wav`：约 10 秒不与他人重叠的语音，作为本人参考声音。

AISHELL-4 没有头戴麦录音，层名里的编号也只在一场之内有效（每场都从 001 编起），所以参考声音只能取同一场的
远场语音。这里取第 4 通道（阵列另一侧的麦克风），避免与被评的第 0 通道逐样本相同，但内容仍与被评录音重叠，
认领结果偏乐观。说话人记为 `<场次>-<层名>`，在所有场次里唯一。

场次名形如 `L_R003S01C02`。同一 `R003` 下的各场（不论 L/M/S 前缀）可能是同一批人，所以 `group` 取 `R003`，
评测找“不在场的人”时跳过同组场次，免得把同一个人当成缺席者。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import wave
from pathlib import Path

import numpy as np

RATE = 16000
CHANNEL = 0
VOICE_CHANNEL = 4
VOICE_SECONDS = 10.0
VOICE_MAX_SECONDS = 20.0
# AISHELL-4 transcription marks (<sil>, <$>, <#>, <->, <%>, ...): silence, noise and fillers, not spoken words.
_MARKS = re.compile(r"<[^<>]*>")
_LONG = re.compile(r'xmin\s*=\s*([-\d.eE]+)\s*xmax\s*=\s*([-\d.eE]+)\s*text\s*=\s*"((?:[^"]|"")*)"', re.MULTILINE)
_GROUP = re.compile(r"R\d+(?=S\d+)")
_TIER = re.compile(r'class\s*=\s*"IntervalTier"\s*name\s*=\s*"((?:[^"]|"")*)"')


def clean_text(text: str) -> str:
    return " ".join(_MARKS.sub(" ", text).split())


def read_textgrid(path: Path, session: str) -> list[dict]:
    """Turns {start, end, speaker, text} from a long-format TextGrid, one IntervalTier per speaker; blank dropped."""
    raw = path.read_bytes()
    content = raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig")
    starts = [(m.start(), m.group(1).replace('""', '"').strip()) for m in _TIER.finditer(content)]
    if not starts:
        raise ValueError(f"{path.name} 不是长格式 IntervalTier TextGrid")
    turns = []
    for k, (offset, tier) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(content)
        for m in _LONG.finditer(content, offset, end):
            text = clean_text(m.group(3).replace('""', '"'))
            if text:
                turns.append(
                    {
                        "start": round(float(m.group(1)), 3),
                        "end": round(float(m.group(2)), 3),
                        "speaker": f"{session}-{tier}",
                        "text": text,
                    }
                )
    return sorted(turns, key=lambda t: (t["start"], t["end"], t["speaker"]))


def isolated(turns: list[dict]) -> list[dict]:
    """Turns that overlap no other speaker's turn."""
    return [
        t
        for t in turns
        if not any(o["speaker"] != t["speaker"] and o["start"] < t["end"] and t["start"] < o["end"] for o in turns)
    ]


def voice_sample(samples: np.ndarray, turns: list[dict], speaker: str) -> np.ndarray | None:
    """About VOICE_SECONDS of the speaker's isolated speech, longest turns first, capped at VOICE_MAX_SECONDS."""
    own = [t for t in isolated(turns) if t["speaker"] == speaker]
    own.sort(key=lambda t: (t["start"] - t["end"], t["start"]))
    pieces, total = [], 0.0
    for turn in own:
        if total >= VOICE_SECONDS:
            break
        length = min(turn["end"] - turn["start"], VOICE_MAX_SECONDS - total)
        pieces.append(samples[round(turn["start"] * RATE) : round((turn["start"] + length) * RATE)])
        total += length
    return np.concatenate(pieces) if total >= VOICE_SECONDS / 2 else None


def write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.astype("<i2").tobytes())


def read_channels(path: Path, channels: tuple[int, ...]) -> list[np.ndarray]:
    """Selected channels of a 16 kHz 16-bit FLAC as int16, read a minute at a time."""
    import soundfile

    with soundfile.SoundFile(str(path)) as source:
        if source.samplerate != RATE or source.channels <= max(channels):
            raise ValueError(f"{path.name} 为 {source.samplerate} Hz、{source.channels} 通道，应为 {RATE} Hz、8 通道")
        parts = [[] for _ in channels]
        while len(block := source.read(RATE * 60, dtype="int16", always_2d=True)):
            for k, channel in enumerate(channels):
                parts[k].append(block[:, channel].copy())
    return [np.concatenate(p) for p in parts]


def group_of(session: str) -> str:
    found = _GROUP.search(session)
    if found is None:
        raise ValueError(f"场次名 {session} 里没有 R<编号>S<编号>")
    return found.group()


def prepare(root: Path, out: Path) -> dict[str, int]:
    grids = sorted((root / "TextGrid").glob("*.TextGrid"))
    if not grids:
        raise ValueError(f"{root / 'TextGrid'} 下没有 TextGrid")
    lines, people = [], 0
    for grid in grids:
        session = grid.stem
        audio = root / "wav" / f"{session}.flac"
        if not audio.is_file():
            raise ValueError(f"缺少场次 {session} 的录音")
        turns = read_textgrid(grid, session)
        far, near = read_channels(audio, (CHANNEL, VOICE_CHANNEL))
        write_wav(out / "sessions" / f"{session}.wav", far)
        reference = json.dumps({"segments": turns}, ensure_ascii=False)
        (out / "sessions" / f"{session}.json").write_text(reference, encoding="utf-8")
        references = {}
        for speaker in sorted({t["speaker"] for t in turns}):
            sample = voice_sample(near, turns, speaker)
            if sample is not None:
                write_wav(out / "voices" / f"{speaker}.wav", sample)
                references[speaker] = f"voices/{speaker}.wav"
        people += len(references)
        row = {
            "id": session,
            "audio": f"sessions/{session}.wav",
            "duration": round(len(far) / RATE, 3),
            "reference": f"sessions/{session}.json",
            "references": references,
            "voice_from": {speaker: session for speaker in references},
            "group": group_of(session),
        }
        lines.append(json.dumps(row, ensure_ascii=False))
        print(f"{session}: {len(turns)} 句，{len(references)} 人有参考声音", file=sys.stderr, flush=True)
    (out / "sessions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"sessions": len(lines), "people": people}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", type=Path, help="解压后的 test 目录（含 wav/ 与 TextGrid/）")
    parser.add_argument("--out", type=Path, required=True, help="输出目录（放在仓库外）")
    args = parser.parse_args()
    try:
        summary = prepare(args.root.expanduser(), args.out.expanduser())
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
