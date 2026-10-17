"""OpenAI-compatible ``/v1/embeddings`` for twin, resident on the GPU machine next to the transcription service.

    python embed.py --model <local BAAI/bge-m3 directory> [--host 127.0.0.1] [--port 18791] [--device cuda]

Dense bge-m3 vectors: the [CLS] state of the last layer, L2-normalised, the same space as other bge-m3 endpoints.
Texts are sorted by length and encoded in passes of at most ``TOKENS_PER_PASS`` padded tokens, so a batch of long
texts never needs more than a fixed slice of GPU memory, and that memory goes back to the GPU after each request:
the card is shared with transcription (and at times a language model). Requests are encoded one at a time.
No key: the port is bound to loopback and reached only through the reverse tunnel on daw's loopback.
"""

from __future__ import annotations

import argparse
import json
import threading
from collections.abc import Callable, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

VERSION = "1.0.0"
MAX_LENGTH = 8192
TOKENS_PER_PASS = 8192
MAX_INPUTS = 256
MAX_BODY = 16 * 1024 * 1024

Encode = Callable[[list[str]], list[list[float]]]


def passes(lengths: Sequence[int], budget: int = TOKENS_PER_PASS) -> list[list[int]]:
    """Indices grouped into passes, longest first, whose padded size (count x longest) stays within ``budget``; a
    text longer than the budget goes alone."""
    order = sorted(range(len(lengths)), key=lambda i: -lengths[i])
    groups: list[list[int]] = []
    for index in order:
        if groups and (len(groups[-1]) + 1) * lengths[groups[-1][0]] <= budget:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups


class Encoder:
    def __init__(self, model: Path, device: str) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.device = device
        self.tokenizer = AutoTokenizer.from_pretrained(model)
        dtype = torch.float16 if device.startswith("cuda") else torch.float32
        self.model = AutoModel.from_pretrained(model, dtype=dtype).to(device).eval()

    def __call__(self, texts: list[str]) -> list[list[float]]:
        torch = self.torch
        lengths = [len(ids) for ids in self.tokenizer(texts, truncation=True, max_length=MAX_LENGTH)["input_ids"]]
        vectors: list[list[float]] = [[] for _ in texts]
        with torch.inference_mode():
            for group in passes(lengths):
                batch = self.tokenizer(
                    [texts[i] for i in group],
                    padding=True,
                    truncation=True,
                    max_length=MAX_LENGTH,
                    return_tensors="pt",
                ).to(self.device)
                cls = self.model(**batch).last_hidden_state[:, 0].float()
                cls = torch.nn.functional.normalize(cls, dim=-1).cpu()
                for row, index in enumerate(group):
                    vectors[index] = [round(float(x), 6) for x in cls[row]]
        if self.device.startswith("cuda"):
            torch.cuda.empty_cache()
        return vectors


def embeddings(encode: Encode, name: str, body: Any) -> tuple[int, dict[str, Any]]:
    """The response to one ``POST /v1/embeddings`` body, in the OpenAI shape."""
    if not isinstance(body, dict):
        return 400, error("请求必须是 JSON 对象")
    texts = body.get("input")
    if isinstance(texts, str):
        texts = [texts]
    if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
        return 400, error("input 必须是字符串或非空字符串列表")
    if len(texts) > MAX_INPUTS:
        return 400, error(f"一次最多 {MAX_INPUTS} 条")
    if body.get("encoding_format", "float") != "float":
        return 400, error("只支持 encoding_format=float")
    vectors = encode([t if t.strip() else " " for t in texts])
    return 200, {
        "object": "list",
        "model": name,
        "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


def error(message: str) -> dict[str, Any]:
    return {"error": {"message": message, "type": "invalid_request_error"}}


def serve(encode: Encode, name: str, host: str, port: int, device: str) -> ThreadingHTTPServer:
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/health":
                self.reply(200, {"ok": True, "version": VERSION, "model": name, "device": device})
            elif self.path == "/v1/models":
                self.reply(200, {"object": "list", "data": [{"id": name, "object": "model"}]})
            else:
                self.reply(404, error("not found"))

        def do_POST(self) -> None:
            if self.path != "/v1/embeddings":
                self.reply(404, error("not found"))
                return
            size = int(self.headers.get("Content-Length") or 0)
            if size <= 0 or size > MAX_BODY:
                self.reply(413, error("请求体为空或过大"))
                return
            try:
                body = json.loads(self.rfile.read(size))
            except ValueError:
                self.reply(400, error("请求不是有效的 JSON"))
                return
            try:
                with lock:
                    status, payload = embeddings(encode, name, body)
            except Exception as exc:  # The service stays up; the caller retries or falls back.
                status, payload = 500, {"error": {"message": type(exc).__name__, "type": "server_error"}}
            self.reply(status, payload)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--name", default="BAAI/bge-m3")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18791)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    encoder = Encoder(args.model, args.device)
    encoder(["预热"])
    print(f"embed {VERSION} {args.name} on {args.device} at http://{args.host}:{args.port}", flush=True)
    serve(encoder, args.name, args.host, args.port, args.device).serve_forever()


if __name__ == "__main__":
    main()
