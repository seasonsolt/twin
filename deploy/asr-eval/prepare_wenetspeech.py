# /// script
# requires-python = ">=3.12"
# dependencies = ["pyarrow>=15", "soundfile>=0.12"]
# ///
"""把 Hugging Face lmms-lab-audio/WenetSpeech 的 parquet（如 test_meeting）转成 ASR 评测清单。

    uv run deploy/asr-eval/prepare_wenetspeech.py <parquet>... --out <仓库外目录>

输出 <out>/audio/<id>.wav（16 kHz 单声道 PCM）和 <out>/manifest.jsonl，每行 {id, audio, text, duration}。
"""

import argparse
import io
import json
from pathlib import Path

import pyarrow.parquet as pq
import soundfile as sf


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("parquet", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    audio_dir = args.out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    rows, hours = [], 0.0
    for path in args.parquet:
        for row in pq.read_table(path, columns=["utt_id", "audio", "text"]).to_pylist():
            data, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
            if rate != 16000:
                raise SystemExit(f"{row['utt_id']} 采样率 {rate}，应为 16000")
            sf.write(audio_dir / f"{row['utt_id']}.wav", data, rate, subtype="PCM_16")
            duration = len(data) / rate
            hours += duration / 3600
            rows.append(
                {
                    "id": row["utt_id"],
                    "audio": f"audio/{row['utt_id']}.wav",
                    "text": row["text"],
                    "duration": round(duration, 4),
                }
            )
    manifest = args.out / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)} 条，{hours:.2f} 小时 → {manifest}")


if __name__ == "__main__":
    main()
