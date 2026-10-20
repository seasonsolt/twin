"""Eval-only L4: clean public cached transcripts, then replay through eval-asr-session.

prepare reads only manifest IDs/durations and cached hypotheses, never reference transcripts or audio.
replay implements CommandTranscriber's protocol without contacting ASR or the LLM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from twin.evals.diarization import edit_distance


def cache_key(**values: Any) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
        stream.write(text)
    temporary.replace(path)


def apply_edits(
    segments: list[dict[str, Any]], payload: Any, allowed: set[int], guard: float
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict) or set(payload) != {"edits"} or not isinstance(payload["edits"], list):
        raise ValueError("Expected an edits object")
    result = [dict(segment) for segment in segments]
    seen: set[int] = set()
    rejected = 0
    for edit in payload["edits"]:
        if not isinstance(edit, dict) or set(edit) != {"id", "text"}:
            raise ValueError("Invalid edit fields")
        index, text = edit["id"], edit["text"]
        if type(index) is not int or index not in allowed or index in seen or not isinstance(text, str):
            raise ValueError("Invalid or duplicate edit ID/text")
        seen.add(index)
        old = segments[index]["text"]
        # Ignore punctuation in the guard, just as CER does; never accept an empty replacement.
        left = "".join(c for c in old if c.isalnum())
        right = "".join(c for c in text if c.isalnum())
        if not right or edit_distance(left, right) / max(1, len(left)) > guard:
            rejected += 1
        else:
            result[index]["text"] = text
    return result, rejected


def replay(cache: Path, request: dict[str, Any]) -> dict[str, Any]:
    session = Path(request["audio"]).stem
    views = {row["target"]: row for row in read_rows(cache) if row["session"] == session}
    target = Path(request["reference"]).stem if request.get("reference") else ""
    if target not in views:
        raise ValueError("Missing cached session/voice; refusing to run ASR")
    base = views[target]
    speakers = [dict(speaker) for speaker in base["speakers"]]
    for speaker in speakers:
        similarities = {}
        for name in request.get("references", {}):
            if name not in views:
                raise ValueError("Missing cached voice view")
            other = next(s for s in views[name]["speakers"] if s["id"] == speaker["id"])
            similarities[name] = other["similarity"]
        if similarities:
            speaker["similarities"] = similarities
    return {"ok": True, "segments": base["segments"], "speakers": speakers}


def complete(*, config: dict[str, Any], prompt: str, user: str, effort: str, cache: Path) -> dict[str, Any]:
    key = cache_key(model=config["model"], prompt=prompt, user=user, effort=effort, endpoint=config["base_url"])
    path = cache / (key + ".json")
    if path.exists():
        return {**json.loads(path.read_text()), "cached": True}
    began = time.monotonic()
    # No response bodies or exception messages in errors: upstream diagnostics can contain credentials.
    for attempt in range(5):
        delay = 30 * 2**attempt
        try:
            response = httpx.post(
                config["base_url"].rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + os.environ[config.get("api_key_env", "TWIN_LLM_KEY")]},
                json={
                    "model": config["model"],
                    "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                    "reasoning_effort": effort,
                    "max_tokens": 8192,
                    "response_format": {"type": "json_object"},
                },
                timeout=600,
            )
        except httpx.HTTPError as error:
            failure = f"LLM transport failed: {type(error).__name__}"
        else:
            if response.is_success:
                break
            failure = f"LLM HTTP {response.status_code}"
            if response.status_code not in (408, 429) and response.status_code < 500:
                raise RuntimeError(failure)
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                delay = max(delay, int(retry_after))
        if attempt == 4:
            raise RuntimeError(failure)
        print(f"{failure}; retry {attempt + 1}/4 after {delay}s", file=sys.stderr, flush=True)
        time.sleep(delay)
    body = response.json()
    choice = body["choices"][0]
    if choice["finish_reason"] != "stop":
        raise RuntimeError("LLM did not finish normally")
    result = {
        "payload": json.loads(choice["message"]["content"]),
        "usage": body.get("usage", {}),
        "seconds": time.monotonic() - began,
        "attempts": attempt + 1,
        "key": key,
    }
    private_write(path, json.dumps(result, ensure_ascii=False))
    return {**result, "cached": False}


def prepare(args: argparse.Namespace) -> None:
    if not args.public_alimeeting:
        raise ValueError("Explicit --public-alimeeting confirmation required; never use private recordings")
    repo = Path(__file__).resolve().parents[2]
    for path in (args.out, args.cache):
        if path.resolve().is_relative_to(repo):
            raise ValueError("Outputs and caches must be outside the repository")
    manifest = read_rows(args.sessions)
    ids = {row["id"] for row in manifest}
    rows = [row for row in read_rows(args.base_cache) if row["session"] in ids]
    sessions: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        previous = sessions.setdefault(row["session"], row["segments"])
        if previous != row["segments"]:
            raise ValueError("Voice views have different hypotheses")
    if set(sessions) != ids:
        raise ValueError("Missing cached sessions")
    config = tomllib.loads(args.config.read_text())["llm"]
    prompt = args.prompt.read_text()
    tasks = [(sid, start) for sid, segs in sessions.items() for start in range(0, len(segs), args.batch)]
    began = time.monotonic()

    def run(task: tuple[str, int]) -> tuple[str, int, dict[str, Any]]:
        sid, start = task
        segs = sessions[sid]
        end = min(start + args.batch, len(segs))
        # --context 0 shows the whole meeting, as the first L4 runs did; otherwise only that many segments around.
        shown = (
            range(0, len(segs))
            if not args.context
            else range(max(0, start - args.context), min(len(segs), end + args.context))
        )
        user = json.dumps(
            {
                "meeting": [{"id": i, "speaker": segs[i]["speaker"], "text": segs[i]["text"]} for i in shown],
                "editable_ids": list(range(start, end)),
            },
            ensure_ascii=False,
        )
        result = complete(config=config, prompt=prompt, user=user, effort=args.effort, cache=args.cache)
        # Validate before marking work successful, even for cache hits.
        apply_edits(segs, result["payload"], set(range(start, end)), args.guard)
        print(f"{sid} {start}:{end} cached={result['cached']}", file=sys.stderr, flush=True)
        return sid, start, result

    cleaned = {sid: [dict(s) for s in segs] for sid, segs in sessions.items()}
    calls = []
    rejected = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for sid, start, result in pool.map(run, tasks):
            end = min(start + args.batch, len(sessions[sid]))
            changed, count = apply_edits(sessions[sid], result["payload"], set(range(start, end)), args.guard)
            cleaned[sid][start:end] = changed[start:end]
            rejected += count
            calls.append({"session": sid, "start": start, **{k: v for k, v in result.items() if k != "payload"}})
    private_write(
        args.out,
        "".join(json.dumps({**row, "segments": cleaned[row["session"]]}, ensure_ascii=False) + "\n" for row in rows),
    )
    private_write(
        args.out.with_suffix(".metrics.json"),
        json.dumps(
            {
                "model": config["model"],
                "effort": args.effort,
                "batch": args.batch,
                "context": args.context,
                "guard": args.guard,
                "prompt_hash": cache_key(prompt=prompt),
                "base_hash": cache_key(rows=rows),
                "wall_seconds": time.monotonic() - began,
                "audio_seconds": sum(row["duration"] for row in manifest),
                "rejected_edits": rejected,
                "changed_segments": sum(
                    a != b for sid in sessions for a, b in zip(sessions[sid], cleaned[sid], strict=True)
                ),
                "calls": calls,
            },
            indent=2,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    replay_parser = commands.add_parser("replay")
    replay_parser.add_argument("--cache", type=Path, required=True)
    prep = commands.add_parser("prepare")
    for name in ("sessions", "base-cache", "config", "out", "cache"):
        prep.add_argument("--" + name, type=Path, required=True)
    prep.add_argument("--prompt", type=Path, default=Path(__file__).with_name("llm_clean_prompt.txt"))
    prep.add_argument("--batch", type=int, default=80)
    prep.add_argument("--context", type=int, default=20)
    prep.add_argument("--workers", type=int, choices=(1, 2), default=2)
    prep.add_argument("--effort", choices=("low", "medium", "high"), default="low")
    prep.add_argument("--guard", type=float, default=0.25)
    prep.add_argument("--public-alimeeting", action="store_true")
    args = parser.parse_args()
    if args.action == "replay":
        print(json.dumps(replay(args.cache, json.load(sys.stdin)), ensure_ascii=False))
    else:
        if args.batch < 1 or args.context < 0 or not 0 <= args.guard <= 1:
            parser.error("batch must be positive, context not negative and guard between 0 and 1")
        prepare(args)


if __name__ == "__main__":
    main()
