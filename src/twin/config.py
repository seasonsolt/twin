"""Settings loaded from a TOML file (default ``twin.toml``). Secrets are never stored here: only the
*name* of the environment variable that holds an API key."""

from __future__ import annotations

import ipaddress
import os
import re
import tomllib
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from .embed import Embedder, HashingEmbedder, OpenAICompatEmbedder, embedder_fingerprint
from .llm import LLM, AnthropicLLM, ClaudeCLILLM, Effort, OpenAICompatLLM
from .media.asr import CloudflareWhisper, OpenAICompatTranscription, SpeechRecognizer
from .media.schema import AVATAR_PRESETS, VoiceSpec
from .media.tts import CloudflareMeloTTS, OpenAICompatSpeech, SilentSynthesizer, SpeechSynthesizer
from .usage import Price
from .util import RenameError, fingerprint, key_from_env

CLAUDE_DEFAULT_MODEL = "claude-opus-5-5"


class LLMSettings(BaseModel):
    """One model endpoint. The default is an OpenAI-compatible endpoint (a private vLLM / SGLang deployment or a
    mainland cloud API): Anthropic and OpenAI do not serve companies headquartered or majority-owned in mainland
    China. ``model`` defaults to Claude only for the anthropic and claude_cli providers."""

    provider: Literal["anthropic", "openai_compat", "claude_cli"] = "openai_compat"
    model: str | None = None
    base_url: str | None = None
    api_key_env: str = "TWIN_LLM_KEY"
    json_mode: Literal["json_schema", "json_object", "none"] = "json_object"
    effort_extract: Effort = "medium"
    effort_twin: Effort = "high"
    max_tokens: int | None = Field(default=None, gt=0)
    timeout: float = Field(default=600.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    egress: Literal["local", "external"] | None = None


class EmbedSettings(BaseModel):
    provider: Literal["openai_compat", "hashing"] = "hashing"
    model: str = "BAAI/bge-m3"
    base_url: str | None = None
    api_key_env: str = "TWIN_EMBED_KEY"
    cluster_threshold: float | None = Field(default=None, gt=0, le=1)
    batch_size: int = Field(default=32, gt=0)
    timeout: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=2, ge=0)
    egress: Literal["local", "external"] | None = None


class TTSSettings(BaseModel):
    """Only preset voice identifiers and credential environment-variable names are stored."""

    provider: Literal["silent", "cloudflare", "openai_compat"] = "silent"
    model: str | None = None
    base_url: str | None = None
    api_key_env: str = "TWIN_TTS_KEY"
    voice: str = "default"
    language: str = "zh"
    timeout: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=2, ge=0)
    egress: Literal["local", "external"] | None = None

    @field_validator("voice")
    @classmethod
    def preset_voice(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value) is None or value in {".", ".."}:
            raise ValueError(
                "仅支持预置音色 ID（1–64 位字母、数字、下划线、点或连字符）；本版本禁止声音复刻（M4 门槛）"
            )
        return value


class AvatarSettings(BaseModel):
    preset: str = "default"

    @field_validator("preset")
    @classmethod
    def stylized_preset(cls, value: str) -> str:
        if value not in AVATAR_PRESETS:
            raise ValueError(f"形象仅支持预置：{'、'.join(AVATAR_PRESETS)}；不支持照片或视频输入（M4 门槛）")
        return value


class ASRSettings(BaseModel):
    """Recognition is opt-in and used only for synthetic speech evaluation."""

    provider: Literal["cloudflare", "openai_compat"] = "openai_compat"
    model: str | None = None
    base_url: str | None = None
    api_key_env: str = "TWIN_ASR_KEY"
    language: str = "zh"
    timeout: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=2, ge=0)
    egress: Literal["local", "external"] | None = None


EgressKind = Literal["llm", "embed", "tts", "asr"]
BackendSettings = LLMSettings | EmbedSettings | TTSSettings | ASRSettings


@dataclass(frozen=True)
class EgressInfo:
    kind: EgressKind
    external: bool
    declared: bool
    host: str | None
    reason: str


def egress_of(section: BackendSettings) -> EgressInfo:
    """Conservative endpoint classification; never expose URL userinfo, paths or queries."""
    kind: EgressKind
    if isinstance(section, LLMSettings):
        kind = "llm"
    elif isinstance(section, EmbedSettings):
        kind = "embed"
    elif isinstance(section, TTSSettings):
        kind = "tts"
    else:
        kind = "asr"
    endpoint = section.base_url
    if section.provider == "openai_compat" and kind in {"llm", "embed"}:
        endpoint = endpoint or os.environ.get("OPENAI_BASE_URL")
    if section.provider == "anthropic":
        endpoint = os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
    host = None
    if endpoint:
        try:
            parsed = urlsplit(endpoint)
            candidate = parsed.hostname
            # Invalid endpoints remain unknown, not arbitrary text in errors or status.
            if (
                parsed.scheme in {"http", "https"}
                and candidate
                and not any(ch.isspace() or ch in "@/?#\\" for ch in candidate)
            ):
                host = candidate
        except ValueError:
            pass
    if section.egress is not None:
        return EgressInfo(kind, section.egress == "external", True, host, "配置显式声明")
    if section.provider in {"hashing", "silent"}:
        return EgressInfo(kind, False, False, host, "本机后端")
    if section.provider in {"anthropic", "claude_cli", "cloudflare"}:
        return EgressInfo(kind, True, False, host, "外部服务")
    loopback = host == "localhost"
    if host:
        with suppress(ValueError):
            loopback = ipaddress.ip_address(host).is_loopback
    return EgressInfo(kind, not loopback, False, host, "本机地址，未声明是否转发" if loopback else "非本机或未知地址")


class BudgetSettings(BaseModel):
    max_cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ApiSettings(BaseModel):
    token_env: str = Field(default="TWIN_API_TOKEN", min_length=1)
    rate_per_minute: int = Field(default=30, gt=0)


class Settings(BaseModel):
    db_path: Path = Path("data/twin.db")
    target_name: str = "本人"
    target_aliases: list[str] = Field(default_factory=list)
    # General twin: other speakers' names in chats and interviews are replaced by stable codes at import.
    pseudonymize_others: bool = True
    max_workers: int = 4
    llm: LLMSettings = Field(default_factory=LLMSettings)
    # Evaluation judges (``[[judges]]`` tables). Empty: the main ``llm`` judges. Use 2-3 models of families
    # other than the twin's, since a judge tends to prefer output resembling its own.
    judges: list[LLMSettings] = Field(default_factory=list)
    embed: EmbedSettings = Field(default_factory=EmbedSettings)
    pricing: dict[str, Price] = Field(default_factory=dict)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    asr: ASRSettings = Field(default_factory=ASRSettings)
    avatar: AvatarSettings = Field(default_factory=AvatarSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)

    def is_target(self, speaker: str) -> bool:
        return speaker == self.target_name or speaker in self.target_aliases


def configuration_fingerprint(
    settings: Settings,
    llm: LLM,
    embedder: Embedder,
    judges: Sequence[tuple[str, Effort]],
    *,
    experiment: Mapping[str, object] | None = None,
) -> str:
    """Identify answer-affecting settings and the actual panel without serializing endpoints or credentials."""
    return fingerprint(
        {
            "llm": {**settings.llm.model_dump(mode="json", exclude={"base_url", "api_key_env"}), "name": llm.name},
            "judges": [{"id": judge_id, "effort": effort} for judge_id, effort in judges],
            "embed": {
                **settings.embed.model_dump(mode="json", exclude={"base_url", "api_key_env"}),
                "fingerprint": embedder_fingerprint(embedder),
                "cluster_threshold": embedder.cluster_threshold,
            },
            "target_name": settings.target_name,
            "target_aliases": settings.target_aliases,
            "pseudonymize_others": settings.pseudonymize_others,
            "experiment": experiment,
        }
    )


def check_config_rename() -> None:
    """Reject obsolete default names rather than silently ignoring existing configuration."""
    if "DTWIN_CONFIG" in os.environ and "TWIN_CONFIG" not in os.environ:
        raise RenameError(
            "环境变量 DTWIN_CONFIG 已改名为 TWIN_CONFIG，请设置 TWIN_CONFIG 并移除 DTWIN_CONFIG；旧名称不再支持"
        )
    if Path("dtwin.toml").is_file() and not Path("twin.toml").is_file():
        raise RenameError("配置文件 dtwin.toml 已改名为 twin.toml，请将 dtwin.toml 重命名为 twin.toml；旧名称不再支持")


def load_settings(path: Path | None = None) -> Settings:
    check_config_rename()
    path = path or Path(os.environ.get("TWIN_CONFIG", "twin.toml"))
    settings = Settings()
    if path.exists():
        with path.open("rb") as f:
            settings = Settings.model_validate(tomllib.load(f))
        settings.db_path = settings.db_path.expanduser()
        if not settings.db_path.is_absolute():
            settings.db_path = path.parent / settings.db_path
    for key_env in [
        settings.llm.api_key_env,
        settings.embed.api_key_env,
        settings.tts.api_key_env,
        settings.asr.api_key_env,
        *[judge.api_key_env for judge in settings.judges],
    ]:
        key_from_env(key_env)
    return settings


def _endpoint(base_url: str | None, section: str) -> str | None:
    """The configured base_url. Without one the OpenAI SDK silently targets the public api.openai.com, so it is
    required unless ``OPENAI_BASE_URL`` names the endpoint explicitly (returning None lets the SDK read it)."""
    if base_url:
        return base_url
    if os.environ.get("OPENAI_BASE_URL"):
        return None
    raise ValueError(
        f'[{section}] provider = "openai_compat" 必须设置 base_url，例如私有化 vLLM / SGLang 服务 '
        '"http://<主机>:8000/v1"，或境内云厂商的 OpenAI 兼容地址（见 twin.toml.example 里的示例）；'
        "否则请求和个人资料会发往公网 api.openai.com"
    )


def make_llm(s: LLMSettings, section: str = "llm") -> LLM:
    """The backend for ``s``. ``section`` names the config table in error messages (e.g. ``judges[1]``)."""
    if s.provider != "claude_cli":
        key_from_env(s.api_key_env)
    if s.provider == "anthropic":
        return AnthropicLLM(model=s.model or CLAUDE_DEFAULT_MODEL, max_tokens=s.max_tokens)
    if s.provider == "openai_compat":
        if not s.model:
            raise ValueError(
                f'[{section}] provider = "openai_compat" 必须设置 model：推理服务里注册的模型名'
                "（vLLM 的 --served-model-name，或云厂商文档里的模型名）"
            )
        return OpenAICompatLLM(
            model=s.model,
            base_url=_endpoint(s.base_url, section),
            api_key_env=s.api_key_env,
            json_mode=s.json_mode,
            max_tokens=s.max_tokens,
            timeout=s.timeout,
            max_retries=s.max_retries,
        )
    return ClaudeCLILLM(model=s.model or CLAUDE_DEFAULT_MODEL)


def make_synthesizer(s: TTSSettings) -> SpeechSynthesizer:
    """Construct a configured backend without selecting an implicit public endpoint."""
    voice = VoiceSpec(voice_id=s.voice, language=s.language, label=s.voice)
    if s.provider == "silent":
        return SilentSynthesizer(voice=voice)
    key_from_env(s.api_key_env)
    if not s.base_url:
        raise ValueError(f'[tts] provider = "{s.provider}" 必须设置 base_url')
    if s.provider == "cloudflare":
        return CloudflareMeloTTS(
            base_url=s.base_url,
            api_key_env=s.api_key_env,
            voice=voice,
            languages=[s.language],
            timeout=s.timeout,
            max_retries=s.max_retries,
        )
    if not s.model:
        raise ValueError('[tts] provider = "openai_compat" 必须设置 model：语音服务里注册的模型名')
    return OpenAICompatSpeech(
        model=s.model,
        base_url=s.base_url,
        api_key_env=s.api_key_env,
        voice=voice,
        timeout=s.timeout,
        max_retries=s.max_retries,
    )


def make_recognizer(s: ASRSettings) -> SpeechRecognizer:
    """Construct an explicit evaluation backend without an implicit public endpoint."""
    key_from_env(s.api_key_env)
    if not s.base_url:
        raise ValueError(f'[asr] provider = "{s.provider}" 必须设置 base_url')
    if s.provider == "cloudflare":
        return CloudflareWhisper(
            base_url=s.base_url,
            api_key_env=s.api_key_env,
            languages=[s.language],
            timeout=s.timeout,
            max_retries=s.max_retries,
        )
    if not s.model:
        raise ValueError('[asr] provider = "openai_compat" 必须设置 model：识别服务里注册的模型名')
    return OpenAICompatTranscription(
        model=s.model,
        base_url=s.base_url,
        api_key_env=s.api_key_env,
        languages=[s.language],
        timeout=s.timeout,
        max_retries=s.max_retries,
    )


def make_embedder(s: EmbedSettings) -> Embedder:
    if s.provider == "openai_compat":
        key_from_env(s.api_key_env)
        return OpenAICompatEmbedder(
            model=s.model,
            base_url=_endpoint(s.base_url, "embed"),
            api_key_env=s.api_key_env,
            cluster_threshold=s.cluster_threshold if s.cluster_threshold is not None else 0.82,
            batch_size=s.batch_size,
            timeout=s.timeout,
            max_retries=s.max_retries,
        )
    if s.cluster_threshold is not None:
        return HashingEmbedder(cluster_threshold=s.cluster_threshold)
    return HashingEmbedder()
