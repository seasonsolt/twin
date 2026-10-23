#!/usr/bin/env python3
"""把 twin 的转写请求转交给另一台机器上常驻的 `run.py --serve`；只用标准库，契约与 run.py 相同。

[asr]
provider = "command"
command = "python3 /path/to/remote.py --url http://127.0.0.1:18790"
"""

import argparse
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False), flush=True)


def report(fraction):
    os.write(2, f"\n@@twin-progress {min(1.0, max(0.0, fraction)):.4f}\n".encode())


def read_hotwords(path):
    if path is None:
        return None
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def build_request(payload, hotwords):
    """Validate twin's stdin request; return (header line, [files to stream])."""
    if not isinstance(payload, dict) or not isinstance(payload.get("audio"), str):
        raise ValueError("请求无效")
    audio = Path(payload["audio"])
    if not audio.is_absolute() or not audio.is_file():
        raise ValueError("音频文件不存在")
    files = [audio]
    reference = payload.get("reference")
    if isinstance(reference, str) and Path(reference).is_absolute() and Path(reference).is_file():
        files.append(Path(reference))
    meta = {
        "language": payload.get("language"),
        "diarize": payload.get("diarize", False),
        "audio_bytes": audio.stat().st_size,
        "reference_bytes": files[1].stat().st_size if len(files) == 2 else 0,
        "audio_suffix": audio.suffix,
    }
    if len(files) == 2:
        meta["reference_suffix"] = files[1].suffix
    references = payload.get("references")
    if isinstance(references, dict):
        voices = [
            (name, Path(path))
            for name, path in references.items()
            if isinstance(path, str) and Path(path).is_absolute() and Path(path).is_file() and Path(path).stat().st_size
        ]
        meta["references"] = [{"name": n, "bytes": path.stat().st_size, "suffix": path.suffix} for n, path in voices]
        files += [path for _, path in voices]
    for key in ("cluster_threshold", "pipeline"):
        if key in payload:
            meta[key] = payload[key]
    if isinstance(payload.get("spans"), list):
        meta["spans"] = payload["spans"]
    if isinstance(payload.get("hotwords"), list):
        meta["hotwords"] = payload["hotwords"]
    elif hotwords:
        meta["hotwords"] = hotwords
    return (json.dumps(meta, ensure_ascii=False) + "\n").encode(), files


def compress(audio, directory):
    """Lossless FLAC is ~40% of twin's 16 kHz PCM wav; upload dominates on a thin link. Any failure sends as is."""
    if audio.suffix.lower() != ".wav" or not shutil.which("ffmpeg"):
        return audio
    target = Path(directory) / "audio.flac"
    command = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(audio), "-c:a", "flac", str(target)]
    try:
        subprocess.run(command, capture_output=True, check=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return audio
    return target if target.is_file() and 0 < target.stat().st_size < audio.stat().st_size else audio


def body(header, files):
    yield header
    for path in files:
        with path.open("rb") as stream:
            while block := stream.read(1 << 20):
                yield block


def address(url):
    parts = urlsplit(url)
    if parts.scheme != "http" or not parts.hostname:
        raise ValueError("转写服务地址无效")
    return parts


def capabilities(url, timeout=30.0):
    """What the service can do besides transcribing (asr-funasr 1.5+); an older one answers without "denoise"."""
    parts = address(url)
    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    try:
        try:
            connection.request("GET", parts.path.rstrip("/") + "/health")
            health = json.loads(connection.getresponse().read())
        except (OSError, ValueError):
            raise ValueError("连不上转写服务，请检查 GPU 机器上的服务和隧道") from None
    finally:
        connection.close()
    return {"ok": True, "version": health.get("version"), "denoise": health.get("denoise") is True}


def denoise(url, payload, *, timeout=3600.0):
    """Have the service denoise ``audio`` for listening and write the FLAC it returns to ``output``."""
    parts = address(url)
    output = payload.get("output")
    if not isinstance(output, str) or not Path(output).is_absolute() or Path(output).suffix != ".flac":
        raise ValueError("output 必须是 .flac 的绝对路径")
    header, files = build_request(payload, None)
    length = len(header) + sum(path.stat().st_size for path in files)
    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    try:
        response = request(connection, parts.path.rstrip("/") + "/denoise", header, files, length)
        result = results(response)
        if result.get("ok") is not True:
            return result
        size = result.get("audio_bytes")
        if not isinstance(size, int) or size <= 0:
            raise ValueError("转写服务返回无效结果")
        target = Path(output)
        temporary = target.with_name(f".{target.name}.tmp")
        with temporary.open("wb") as stream:
            remaining = size
            while remaining:
                block = response.read(min(remaining, 1 << 20))
                if not block:
                    temporary.unlink(missing_ok=True)
                    raise ValueError("转写服务中途断开")
                stream.write(block)
                remaining -= len(block)
        temporary.replace(target)
        return {key: value for key, value in result.items() if key != "audio_bytes"}
    finally:
        connection.close()


# Seconds between tries while nothing answers: two minutes in all. A service that restarts (an upgrade, or after the
# system ended it) answers again once its models are loaded, in half a minute; through the SSH tunnel a connection is
# accepted meanwhile and closed without a response. A job is only sent again when the service never answered it.
CONNECT_WAITS = (5.0,) * (int(os.environ.get("TWIN_ASR_CONNECT_SECONDS", "120")) // 5)


class Unreachable(ValueError):
    """The service did not answer the request at all."""


def request(connection, path, header, files, length):
    try:
        connection.request(
            "POST",
            path,
            body=body(header, files),
            headers={"Content-Type": "application/octet-stream", "Content-Length": str(length)},
        )
        response = connection.getresponse()
    except OSError:
        raise Unreachable("连不上转写服务，请检查 GPU 机器上的服务和隧道") from None
    if response.status != 200:
        try:
            error = json.loads(response.read())["error"]
        except (ValueError, KeyError, TypeError):
            error = f"HTTP {response.status}"
        raise ValueError(f"转写服务拒绝请求：{error}")
    return response


def results(response):
    """Progress lines up to the result, which it returns; the response is left at the bytes after that line."""
    while raw := response.readline():
        line = json.loads(raw)
        if "progress" in line:
            report(float(line["progress"]))
        elif "result" in line:
            return line["result"]
    raise ValueError("转写服务中途断开")


def transcribe(url, payload, *, hotwords=None, timeout=3600.0, flac=True):
    parts = address(url)
    build_request(payload, hotwords)
    with tempfile.TemporaryDirectory(prefix="twin-asr-") as directory:
        if flac:
            payload = {**payload, "audio": str(compress(Path(payload["audio"]), directory))}
        return send(parts, payload, hotwords, timeout)


def send(parts, payload, hotwords, timeout):
    header, files = build_request(payload, hotwords)
    length = len(header) + sum(path.stat().st_size for path in files)
    path = parts.path.rstrip("/") + ("/embed" if payload.get("embed") is True else "/transcribe")
    for wait in CONNECT_WAITS:
        try:
            return post(parts, path, header, files, length, timeout)
        except Unreachable:
            time.sleep(wait)
    return post(parts, path, header, files, length, timeout)


def post(parts, path, header, files, length, timeout):
    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    try:
        return results(request(connection, path, header, files, length))
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=os.environ.get("TWIN_ASR_REMOTE_URL", "http://127.0.0.1:18790"))
    parser.add_argument("--hotwords", help="热词文件，每行一个词；# 开头为注释")
    parser.add_argument("--timeout", type=float, default=3600.0, help="单次读写超时（秒）")
    parser.add_argument("--no-flac", action="store_true", help="wav 不先压成 FLAC，原样上传")
    parser.add_argument("--cluster-threshold", type=float, help="评测用：声纹聚类距离阈值，请求未指定时使用")
    parser.add_argument(
        "--pipeline", choices=("classic", "overlap"), help="评测用：让重叠感知的服务按指定流程处理（1.4 起）"
    )
    args = parser.parse_args()
    try:
        request = json.loads(sys.stdin.read())
        if isinstance(request, dict) and args.cluster_threshold is not None:
            request.setdefault("cluster_threshold", args.cluster_threshold)
        if isinstance(request, dict) and args.pipeline is not None:
            request.setdefault("pipeline", args.pipeline)
        if isinstance(request, dict) and request.get("capabilities") is True:
            payload = capabilities(args.url)
        elif isinstance(request, dict) and request.get("denoise") is True:
            payload = denoise(args.url, request, timeout=args.timeout)
        else:
            payload = transcribe(
                args.url,
                request,
                hotwords=read_hotwords(args.hotwords),
                timeout=args.timeout,
                flac=not args.no_flac,
            )
        if not isinstance(payload, dict) or "ok" not in payload:
            raise ValueError("转写服务返回无效结果")
    except Exception as error:
        payload = {"ok": False, "error": str(error) or type(error).__name__}
    emit(payload)
    return 0 if payload.get("ok") is True else 1


if __name__ == "__main__":
    sys.exit(main())
