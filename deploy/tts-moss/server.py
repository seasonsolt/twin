"""CPU-only OpenAI speech shim exposing a fixed, non-person-specific voice allowlist."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import os
import random
import tempfile
import time
import unicodedata
import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from urllib.request import urlopen

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

MODEL_ID = "MOSS-TTS-Nano"
MODEL_REPO = "OpenMOSS-Team/MOSS-TTS-Nano"
MODEL_REVISION = "44502f80dbf9743528fa921cc544d662c685ebec"
AUDIO_REPO = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano"
AUDIO_REVISION = "6aa02b01e445cc585582cf0ba480bc3ea6c8dd68"
PRESET_REVISION = "8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb"
# moss_tts_nano_runtime.py:26-43 at PRESET_REVISION, intersected with its assets/audio/.
# Exclude the real-person preset, non-WAV assets, and references absent at that commit.
PRESET_FILES = {
    "Junhao": "zh_1.wav",
    "Xiaoyu": "zh_3.wav",
    "Yuewen": "zh_4.wav",
    "Lingyu": "zh_6.wav",
    "Ava": "en_2.wav",
    "Bella": "en_3.wav",
    "Adam": "en_4.wav",
    "Yui": "jp_2.wav",
}
MAX_CHARS = 1000
MIN_SECONDS_PER_CHAR = 0.15
MIN_SPEAKABLE_CHARS = 6
MAX_SYNTHESIS_ATTEMPTS = 3
LOGGER = logging.getLogger("uvicorn.error.tts")


def synthesis_seed(revision: str, voice: str, text: str, attempt: int = 0) -> int:
    """Stable uint32 seed for a zero-based attempt; JSON framing is unambiguous."""
    material = json.dumps([revision, voice, text, attempt], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big")


def speakable_characters(text: str) -> int:
    """Count CJK unified/compatibility ideographs, Latin letters and decimal digits after NFKC."""
    return sum(
        char.isdecimal()
        or (char.isalpha() and "LATIN" in unicodedata.name(char, ""))
        or any(
            start <= ord(char) <= end
            for start, end in ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x323AF))
        )
        for char in unicodedata.normalize("NFKC", text)
    )


class Engine(Protocol):
    """Return mono, little-endian signed int16 PCM and its sample rate."""

    def synthesize(self, text: str, voice: str, *, seed: int) -> tuple[bytes, int]: ...

    def voices(self) -> list[str]: ...


class FakeEngine:
    """Deterministic 48 kHz silence, 80 milliseconds per input character."""

    def voices(self) -> list[str]:
        return list(PRESET_FILES)

    def synthesize(self, text: str, voice: str, *, seed: int) -> tuple[bytes, int]:
        if voice not in self.voices():
            raise ValueError("不支持的预置音色")
        rate = 48000
        return b"\0\0" * max(1, round(len(text) * 0.08 * rate)), rate


class MossNanoEngine:
    """Load pinned remote code on CPU; only bundled generic WAV presets are accepted."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or Path(os.environ.get("HF_HOME", "/cache"))
        self._model: Any = None
        self._text_tokenizer: Any = None
        self._audio_tokenizer: Any = None
        self._available_voices: list[str] = []

    def voices(self) -> list[str]:
        return list(self._available_voices)

    def load(self) -> None:
        """Download weights and preset assets at startup, never during image build."""
        if self._model is not None:
            return
        self._load_models()
        self._load_presets()

    def _load_models(self) -> None:
        """Model/tokenizer failures are fatal; preset failures are handled separately."""
        import torch
        from transformers import AutoConfig, AutoModel, AutoModelForCausalLM, AutoTokenizer

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        hub_cache = str(self.cache_dir / "hub")
        model_kwargs = {
            "revision": MODEL_REVISION,
            "code_revision": MODEL_REVISION,
            "trust_remote_code": True,
            "cache_dir": hub_cache,
        }
        config = AutoConfig.from_pretrained(
            MODEL_REPO,
            **model_kwargs,
            attn_implementation="eager",
            local_transformer_attn_implementation="eager",
        )
        model = (
            AutoModelForCausalLM.from_pretrained(
                MODEL_REPO, **model_kwargs, config=config, torch_dtype=torch.float32, attn_implementation="eager"
            )
            .to(device="cpu", dtype=torch.float32)
            .eval()
        )
        text_tokenizer = AutoTokenizer.from_pretrained(MODEL_REPO, **model_kwargs, use_fast=False)
        audio_tokenizer = (
            AutoModel.from_pretrained(
                AUDIO_REPO,
                revision=AUDIO_REVISION,
                code_revision=AUDIO_REVISION,
                trust_remote_code=True,
                cache_dir=hub_cache,
                torch_dtype=torch.float32,
            )
            .to(device="cpu", dtype=torch.float32)
            .eval()
        )
        audio_tokenizer.set_attention_implementation("sdpa")
        audio_tokenizer.set_compute_dtype("fp32")
        self._text_tokenizer = text_tokenizer
        self._audio_tokenizer = audio_tokenizer
        self._model = model

    def _load_presets(self) -> None:
        import soundfile

        preset_dir = self.cache_dir / "presets" / PRESET_REVISION
        self._available_voices = []
        for name, filename in PRESET_FILES.items():
            target = preset_dir / filename
            try:
                preset_dir.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    url = (
                        "https://raw.githubusercontent.com/OpenMOSS/MOSS-TTS-Nano/"
                        f"{PRESET_REVISION}/assets/audio/{filename}"
                    )
                    with tempfile.TemporaryDirectory(dir=preset_dir) as directory:
                        temporary = Path(directory) / "download.wav"
                        with urlopen(url, timeout=120) as source, temporary.open("wb") as output:
                            while chunk := source.read(65536):
                                output.write(chunk)
                        if soundfile.info(str(temporary)).frames == 0:
                            raise ValueError("预置音色资源为空")
                        temporary.replace(target)
                if soundfile.info(str(target)).frames == 0:
                    raise ValueError("预置音色资源为空")
            except Exception:
                LOGGER.warning("preset unavailable: %s", name)
                continue
            self._available_voices.append(name)

    def synthesize(self, text: str, voice: str, *, seed: int) -> tuple[bytes, int]:
        """The caller holds the engine lock, including all global RNG resets."""
        self.load()
        if voice not in self.voices():
            raise ValueError("不支持的预置音色")
        import numpy as np
        import torch

        # Pinned inference has no generator argument; multinomial uses the global RNG.
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        preset = self.cache_dir / "presets" / PRESET_REVISION / PRESET_FILES[voice]
        with tempfile.TemporaryDirectory(prefix="tts-") as directory, torch.inference_mode():
            result = self._model.inference(
                text=text,
                output_audio_path=str(Path(directory) / "output.wav"),
                mode="voice_clone",
                prompt_audio_path=str(preset),
                text_tokenizer=self._text_tokenizer,
                audio_tokenizer=self._audio_tokenizer,
                device="cpu",
                max_new_frames=375,
                do_sample=True,
                voice_clone_max_text_tokens=75,
                tts_max_batch_size=1,
                codec_max_batch_size=1,
            )
            waveform = result["waveform"].detach().cpu().to(torch.float32)
            if waveform.ndim != 2 or waveform.shape[0] != 2 or not torch.isfinite(waveform).all():
                raise ValueError("语音引擎输出无效")
            mono = waveform.mean(dim=0).clamp(-1.0, 1.0)
            pcm = (mono * 32767).round().to(torch.int16).numpy().astype("<i2").tobytes()
            return pcm, int(result["sample_rate"])


class SpeechBody(BaseModel):
    """Reject all vendor extensions, especially audio inputs and cloning controls."""

    model_config = ConfigDict(extra="forbid", strict=True)
    model: str
    input: str
    voice: str
    response_format: str = "wav"


def make_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Encode the engine's mono PCM using only the standard library."""
    if (
        not isinstance(pcm, bytes)
        or not pcm
        or len(pcm) % 2
        or isinstance(sample_rate, bool)
        or not isinstance(sample_rate, int)
        or sample_rate <= 0
    ):
        raise ValueError("语音引擎输出无效")
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(pcm)
    return output.getvalue()


def create_app(engine: Engine | None = None) -> FastAPI:
    """Build an isolated app; importing this module never imports ML dependencies."""
    selected_engine = engine if engine is not None else MossNanoEngine()
    lock = Lock()
    api_key = os.environ.get("SHIM_API_KEY", "").encode("utf-8")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if isinstance(selected_engine, MossNanoEngine):
            with lock:
                try:
                    selected_engine.load()
                except Exception:
                    LOGGER.error("TTS startup failed: model/tokenizer load failure")
                    raise RuntimeError("TTS startup failed: model/tokenizer load failure") from None
        yield

    application = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def require_auth(request: Request) -> None:
        if api_key:
            header = request.headers.get("authorization", "")
            scheme, _, credential = header.partition(" ")
            matched = hmac.compare_digest(credential.encode("utf-8"), api_key)
            if scheme.lower() != "bearer" or not matched:
                raise HTTPException(401, "需要有效的 Bearer 令牌", headers={"WWW-Authenticate": "Bearer"})

    @application.exception_handler(RequestValidationError)
    async def invalid_body(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "请求格式无效；仅接受规定的文本语音字段"})

    @application.get("/healthz", dependencies=[Depends(require_auth)])
    def health() -> JSONResponse:
        with lock:
            available = bool(selected_engine.voices())
        if not available:
            return JSONResponse(status_code=503, content={"status": "degraded", "reason": "no voices available"})
        return JSONResponse(content={"status": "ok"})

    @application.get("/v1/models", dependencies=[Depends(require_auth)])
    def models() -> dict[str, object]:
        return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "local"}]}

    @application.get("/v1/voices", dependencies=[Depends(require_auth)])
    def voices() -> dict[str, object]:
        with lock:
            names = selected_engine.voices()
        return {"voices": names}

    @application.post("/v1/audio/speech", dependencies=[Depends(require_auth)])
    def speech(body: SpeechBody) -> Response:
        if len(body.input) > MAX_CHARS:
            raise HTTPException(413, "输入超过 1000 字符，请分段合成")
        if not body.input.strip():
            raise HTTPException(400, "输入文本不能为空")
        if body.model != MODEL_ID:
            raise HTTPException(400, "不支持的语音模型")
        if body.response_format != "wav":
            raise HTTPException(400, "仅支持 wav；此镜像未安装 ffmpeg，不支持 mp3")
        started = time.perf_counter()
        attempts = 0
        headers = {"Cache-Control": "no-store"}
        count = speakable_characters(body.input)
        try:
            with lock:
                if body.voice not in selected_engine.voices():
                    raise HTTPException(400, "不支持的预置音色，请查询 /v1/voices")
                longest_duration = -1.0
                encoded = b""
                for attempt in range(MAX_SYNTHESIS_ATTEMPTS):
                    attempts += 1
                    seed = synthesis_seed(MODEL_REVISION, body.voice, body.input, attempt)
                    pcm, rate = selected_engine.synthesize(body.input, body.voice, seed=seed)
                    candidate = make_wav(pcm, rate)  # Validate before computing duration.
                    duration = len(pcm) / (2 * rate)
                    if count < MIN_SPEAKABLE_CHARS or duration / count >= MIN_SECONDS_PER_CHAR:
                        encoded = candidate
                        break
                    if duration > longest_duration:
                        longest_duration, encoded = duration, candidate
                else:
                    headers["X-Speech-Warning"] = "possibly-truncated"
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "语音引擎暂不可用，请稍后重试") from None
        finally:
            LOGGER.info(
                "speech chars=%d attempts=%d elapsed_s=%.3f", len(body.input), attempts, time.perf_counter() - started
            )
        return Response(content=encoded, media_type="audio/wav", headers=headers)

    return application


app = create_app()
