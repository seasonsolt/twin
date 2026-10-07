"""Run with: uv run python scripts/chat_latency.py http://127.0.0.1:8765 --persona default.

For an authenticated app, supply the session cookie in TWIN_SESSION (never in source or command arguments).
Each of the five questions is a normal, persisted chat turn against the running app.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import httpx

QUESTIONS = [
    "你好，简单介绍一下自己。",
    "你最近在忙什么？",
    "遇到难事你会怎么做？",
    "你最看重什么？",
    "你周末一般怎么过？",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure streaming chat first-delta and final latency for five questions"
    )
    parser.add_argument("base_url", nargs="?", default="http://127.0.0.1:8765")
    parser.add_argument("--persona", default="default")
    parser.add_argument("--questions", nargs=5, default=QUESTIONS)
    args = parser.parse_args()
    headers = {"X-Twin": "1", "X-Twin-Persona": args.persona, "Accept": "text/event-stream"}
    cookies = {"twin_session": os.environ["TWIN_SESSION"]} if os.environ.get("TWIN_SESSION") else {}
    with httpx.Client(headers=headers, cookies=cookies, timeout=180) as client:
        for index, question in enumerate(args.questions, 1):
            start = time.perf_counter()
            first: float | None = None
            final: float | None = None
            event, data = "", []
            print(f"{index}/5 {question}", flush=True)
            with client.stream(
                "POST",
                args.base_url.rstrip("/") + "/api/persona/chat/stream",
                json={"messages": [{"role": "user", "content": question}]},
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        payload = json.loads("\n".join(data))
                        elapsed = time.perf_counter() - start
                        if event == "error":
                            raise SystemExit(f"  error: {payload.get('detail', 'stream failed')}")
                        if event == "delta" and payload.get("text") and first is None:
                            first = elapsed
                            print(f"  first delta: {first:.3f}s", flush=True)
                        if event == "final":
                            final = elapsed
                            print(f"  final:       {final:.3f}s", flush=True)
                            break
                        event, data = "", []
            if first is None or final is None:
                raise SystemExit("  stream ended without a first delta and final")


if __name__ == "__main__":
    main()
