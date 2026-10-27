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
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, JsonValue, field_validator, model_validator

if TYPE_CHECKING:
    from .media.video import VideoSynthesizer

from .embed import Embedder, HashingEmbedder, OpenAICompatEmbedder, embedder_fingerprint
from .llm import LLM, AnthropicLLM, ClaudeCLILLM, Effort, FallbackLLM, OpenAICompatLLM
from .media.asr import CloudflareWhisper, OpenAICompatTranscription, SpeechRecognizer
from .media.schema import AVATAR_ALIASES, AVATAR_PRESETS, VoiceSpec
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
    hedge_after_s: float = Field(default=2.5, ge=0, allow_inf_nan=False)
    max_retries: int = Field(default=2, ge=0)
    # The most calls sent to this endpoint at once; the others wait their turn here. Only ``[llm_fallback]`` reads
    # it, at every call, so an administrator's change applies at once: an endpoint kept for emergencies tends to
    # serve few at a time, and proofreading alone asks 16 at a time, which a small gateway queues past its timeout.
    max_concurrent: int = Field(default=4, gt=0)
    extra_body: dict[str, JsonValue] = Field(default_factory=dict)
    egress: Literal["local", "external"] | None = None
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None
    reasoning_effort_extract: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None

    @property
    def effective_reasoning_effort_extract(self) -> str | None:
        if self.reasoning_effort_extract is not None:
            return self.reasoning_effort_extract
        return "low" if self.reasoning_effort == "none" else self.reasoning_effort


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
    """Preset fallback, optional shared reference directory, and credential environment-variable names."""

    provider: Literal["silent", "cloudflare", "openai_compat"] = "silent"
    model: str | None = None
    base_url: str | None = None
    api_key_env: str = "TWIN_TTS_KEY"
    voice: str = "default"
    voice_dir: Path | None = None
    streaming: bool = True
    language: str = "zh"
    timeout: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=2, ge=0)
    egress: Literal["local", "external"] | None = None

    @field_validator("voice")
    @classmethod
    def preset_voice(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value) is None or value in {".", ".."}:
            raise ValueError("仅支持预置音色 ID（1–64 位字母、数字、下划线、点或连字符）")
        return value


class VideoSettings(BaseModel):
    require_assets: bool = Field(default=False, exclude=True)
    provider: Literal["none", "remote"] = "none"
    host: str | None = None
    command: str | None = None
    timeout_s: float = Field(default=3600, gt=0, allow_inf_nan=False)
    max_rounds: int = Field(default=4, ge=1, strict=True)
    max_cer: float = Field(default=0.05, ge=0, allow_inf_nan=False)
    pause_s: float = Field(default=0.25, ge=0, allow_inf_nan=False)
    egress: Literal["local", "external"] | None = None

    @field_validator("host")
    @classmethod
    def ssh_alias(cls, value: str | None) -> str | None:
        if value and (re.fullmatch(r"[A-Za-z0-9._-]{1,64}", value) is None or value.startswith("-")):
            raise ValueError("视频主机须为 SSH 别名，不能包含路径或选项")
        return value

    @model_validator(mode="after")
    def remote_config(self) -> VideoSettings:
        if self.provider == "remote" and (not self.command or not self.command.strip()):
            raise ValueError("[video] 视频须配置非空 command")
        return self


class MediaSettings(BaseModel):
    font_path: str | None = None


class LibrarySettings(BaseModel):
    """An account's recording library: uploads are refused unless ``headroom_gb`` stays free after every file still
    arriving, and at most ``max_pending`` recordings wait to be transcribed at once. The language-model tokens a
    library spends (proofreading its transcripts, and rebuilding its twins) are limited to ``batch_tokens`` in any
    ``batch_hours``; once spent, proofreading and rebuilds wait until the window frees up. 0 means no limit.
    The original of a recording whose transcription failed is kept for a retry; with ``failed_keep_days`` set, it is
    deleted that many days after the failure. 0 (the default) keeps it for good: a failure may be the transcription
    service being down, and a deleted original cannot be had back.
    With ``auto_build`` off, what changes a twin's recordings is noted but its memory is not rebuilt until it is
    switched on again or someone rebuilds that twin: for a large batch of meetings coming in, so each twin is rebuilt
    once at the end rather than after every recording. Meanwhile a twin whose change only adds recordings keeps
    answering from the memory it has; one that lost or had speech reassigned waits (``persona.gate``)."""

    auto_build: bool = True
    headroom_gb: float = Field(default=20, ge=0)
    max_pending: int = Field(default=20, gt=0)
    batch_tokens: int = Field(default=20_000_000, ge=0)
    batch_hours: float = Field(default=24, gt=0)
    failed_keep_days: int = Field(default=0, ge=0)


class AvatarSettings(BaseModel):
    preset: str = "chestnut"
    vrm_path: str | None = None
    image_path: str | None = None

    @field_validator("image_path")
    @classmethod
    def local_image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = Path(value).expanduser()
        try:
            if not path.exists():
                raise ValueError("肖像图片文件不存在")
            if not path.is_file():
                raise ValueError("肖像图片路径必须是文件")
            suffix = path.suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise ValueError("肖像图片后缀必须为 .png、.jpg、.jpeg 或 .webp")
            if path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("肖像图片文件不能超过 10 MB")
            with path.open("rb") as image:
                header = image.read(12)
            valid = (
                header.startswith(b"\x89PNG\r\n\x1a\n")
                if suffix == ".png"
                else header.startswith(b"\xff\xd8\xff")
                if suffix in {".jpg", ".jpeg"}
                else header[:4] == b"RIFF" and header[8:12] == b"WEBP"
            )
            if not valid:
                raise ValueError("肖像图片必须包含与后缀匹配的真实图片魔数")
        except OSError:
            raise ValueError("无法读取肖像图片文件") from None
        return str(path.resolve())

    @field_validator("vrm_path")
    @classmethod
    def local_vrm(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = Path(value).expanduser()
        try:
            if not path.exists():
                raise ValueError("VRM 模型文件不存在")
            if not path.is_file():
                raise ValueError("VRM 模型路径必须是文件")
            if path.suffix.lower() != ".vrm":
                raise ValueError("模型文件后缀必须为 .vrm")
            if path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("VRM 模型文件不能超过 64 MB")
            with path.open("rb") as model:
                if model.read(4) != b"glTF":
                    raise ValueError("VRM 模型必须以 glTF 二进制标记开头")
        except OSError:
            raise ValueError("无法读取 VRM 模型文件") from None
        return str(path.resolve())

    @field_validator("preset")
    @classmethod
    def stylized_preset(cls, value: str) -> str:
        value = AVATAR_ALIASES.get(value, value)
        if value not in AVATAR_PRESETS:
            raise ValueError(f"形象仅支持预置：{'、'.join(AVATAR_PRESETS)}")
        return value


class ASRSettings(BaseModel):
    """Opt-in recognition for media memories and synthetic speech evaluation."""

    provider: Literal["cloudflare", "openai_compat", "command"] = "openai_compat"
    command: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key_env: str = "TWIN_ASR_KEY"
    language: str = "zh"
    timeout: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=2, ge=0)
    egress: Literal["local", "external"] | None = None
    # Proofread each media transcript with [llm] before speakers are claimed; sends the transcript text to [llm].
    clean: bool = True
    # Whether the command hands requests to a resident service that hears them one at a time, so the recording
    # library sends the next recording while one is heard; unset: when the command is asr-funasr's remote.py. A
    # command that loads the models itself must not run twice at once.
    ahead: bool | None = None

    def takes_turns(self) -> bool:
        if self.ahead is not None:
            return self.ahead
        return self.provider == "command" and "remote.py" in (self.command or "")


class VisionSettings(BaseModel):
    provider: Literal["command"] = "command"
    command: str | None = None
    egress: Literal["local", "external"] | None = None


class SearchSettings(BaseModel):
    """Web search and page reading for work mode, through DeepSeek's ``/v1/tools/search`` and ``/v1/tools/fetch``.
    The key is ``api_key_env``, or else the key of ``[chat_llm]`` / ``[llm]`` when it is served from the same
    host, so a twin answering with DeepSeek searches without more configuration. No key: work runs without it."""

    enabled: bool = True
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "TWIN_SEARCH_KEY"
    count: int = Field(default=8, ge=1, le=50)
    timeout: float = Field(default=30.0, gt=0, allow_inf_nan=False)

    @field_validator("base_url")
    @classmethod
    def _encrypted(cls, value: str) -> str:
        """The key goes in every request: only over HTTPS, unless the service is on this machine."""
        parsed = urlsplit(value.strip())
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not parsed.hostname or (parsed.scheme != "https" and not (parsed.scheme == "http" and local)):
            raise ValueError("[search] base_url 必须是 https 地址（本机服务可以用 http）")
        return value.strip()


EgressKind = Literal["llm", "embed", "tts", "asr", "video", "vision"]
BackendSettings = LLMSettings | EmbedSettings | TTSSettings | ASRSettings | VideoSettings | VisionSettings


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
    if isinstance(section, VisionSettings):
        return EgressInfo("vision", section.egress == "external", section.egress is not None, None, "本机命令")
    if isinstance(section, VideoSettings):
        external = (
            section.provider == "remote" and bool(section.host)
            if section.egress is None
            else section.egress == "external"
        )
        return EgressInfo(
            "video",
            external,
            section.egress is not None,
            section.host,
            "配置显式声明"
            if section.egress
            else "SSH 主机默认视为外部"
            if external
            else "本机命令"
            if section.provider == "remote"
            else "未启用",
        )
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
    if section.provider in {"hashing", "silent", "command"}:
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


class SMTPSettings(BaseModel):
    host: str = ""
    port: Literal[465, 587] = 465
    username: str = ""
    from_address: str = ""
    from_name: str = "twin"
    password_env: str = "TWIN_SMTP_PASSWORD"


class SSOSettings(BaseModel):
    """Single sign-on borrowed from another app on the same host (e.g. audio-studio's 认证中心 login).

    twin forwards that app's session cookie, server to server, to `me_url` and trusts the account it reports;
    the browser never hands twin an identity. twin's own sign-in page offers it as one button: a form posted to
    `start_url` (that app's endpoint that hands the browser to the company sign-in and back), or, without one, a
    link to `login_url`, that app's sign-in page. Signing out of twin also ends that app's session on this site.
    `start_url` answers with a redirect to the company sign-in, which the browser follows only when twin's pages
    allow forms to lead there: `sign_in_origin` names it (e.g. https://center.example.com), and without it the
    button stays a link to `login_url`. Signing out also ends the company sign-in when `logout_url` names its sign-out
    page with the way back to twin (e.g. https://auth.example.com/sso/signout?back=https://example.com/twin/);
    without it, the next sign-in passes straight through as the same person.
    """

    me_url: str = ""
    login_url: str = ""
    start_url: str = ""
    sign_in_origin: str = ""
    logout_url: str = ""
    cookie: str = ""
    cache_seconds: int = Field(default=60, ge=0, le=3600)


class AuthSettings(BaseModel):
    enabled: bool = False
    provider: Literal["email", "sso", "password"] = "email"
    # Accounts and passwords kept by twin itself (`twin account add`), besides the provider's sign-in; always on
    # with provider = "password".
    password_login: bool = False
    allowed_domains: list[str] = Field(default_factory=lambda: ["xjjk.com"])
    allowed_emails: list[str] = Field(default_factory=lambda: ["seasonsolt@gmail.com"])
    # Addresses, SSO subjects (sso:<subject>) or SSO account names; an address in an allowed domain also matches the
    # SSO account named by its part before the @.
    admin_emails: list[str] = Field(default_factory=lambda: ["zhangxun@xjjk.com", "qianjinwen@xjjk.com"])
    session_days: int = Field(default=30, gt=0)
    # 0: no limit (internal deployments).
    max_personas_per_member: int = Field(default=3, ge=0)
    smtp: SMTPSettings = Field(default_factory=SMTPSettings)
    sso: SSOSettings = Field(default_factory=SSOSettings)

    @field_validator("allowed_domains", "allowed_emails", "admin_emails")
    @classmethod
    def lowercase(cls, values: list[str]) -> list[str]:
        return [value.strip().lower() for value in values]

    @model_validator(mode="after")
    def smtp_required(self) -> AuthSettings:
        if self.enabled and self.provider == "sso":
            sso = self.sso
            if not re.fullmatch(r"https?://[^/\s]+/\S*", sso.me_url):
                raise ValueError("[auth.sso] me_url 必须是 http(s) 地址，例如 http://127.0.0.1:8765/api/auth/me")
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", sso.cookie):
                raise ValueError("[auth.sso] cookie 必须是另一个应用的会话 cookie 名")
            for key, value in (("login_url", sso.login_url), ("start_url", sso.start_url)):
                if (value or key == "login_url") and (not value.startswith("/") or value.startswith("//")):
                    raise ValueError(f"[auth.sso] {key} 必须是本站路径，例如 /login?next=/twin/")
            if sso.sign_in_origin and not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d{1,5})?", sso.sign_in_origin):
                raise ValueError("[auth.sso] sign_in_origin 必须是认证中心的源，例如 https://center.example.com")
            if sso.logout_url and not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d{1,5})?/\S*", sso.logout_url):
                raise ValueError(
                    "[auth.sso] logout_url 必须是认证中心的登出地址，例如 https://auth.example.com/sso/signout?back=…"
                )
            return self
        if (
            self.enabled
            and self.provider == "email"
            and not all(
                value.strip()
                for value in (self.smtp.host, self.smtp.username, self.smtp.from_address, self.smtp.password_env)
            )
        ):
            raise ValueError("[auth] enabled = true 必须配置 [auth.smtp] host、username、from_address、password_env")
        return self


class WeComSettings(BaseModel):
    url: str = "wss://openws.work.weixin.qq.com"
    # The company's WeCom contacts, to give a twin made for an employee number its member's profile photo
    # (``web.wecom_photos``): the corp ID, and the environment variable holding the secret of an app allowed to read
    # members (the contacts sync secret, say). Without both, no photo is fetched.
    corp_id: str | None = None
    contacts_secret_env: str = "TWIN_WECOM_CONTACTS_SECRET"
    api: str = "https://qyapi.weixin.qq.com"


# The most model calls a memory build may have in flight: its worker pools are this large, and ``max_concurrent``
# lets through as many of them as it says at a time.
MAX_BUILD_CONCURRENT = 64


class KernelSettings(BaseModel):
    auto_rebuild: bool = True
    max_auto_rebuild_chunks: int = Field(default=400, ge=0)
    # The most model calls a memory build sends at once. Read at every call, so an administrator's change applies to
    # a build already running; unset, it is ``max_workers``.
    max_concurrent: int = Field(default=4, gt=0, le=MAX_BUILD_CONCURRENT)


class OpsSettings(BaseModel):
    web_port: int = Field(default=8765, ge=1, le=65535)
    allow_hosts: list[str] = Field(default_factory=list)
    compute_services: dict[str, list[str]] = Field(default_factory=dict)
    tunnel_command: list[str] = Field(default_factory=list)
    # The keyword indexes chat keeps between questions, about this many MB for all twins together; a twin with a
    # hundred thousand expressions takes some 70. The latest one is kept whatever its size.
    keyword_index_mb: int = Field(default=192, ge=0)


class UpgradeSettings(BaseModel):
    channel: Literal["off", "stable", "canary"] = "off"


class Settings(BaseModel):
    db_path: Path = Path("data/twin.db")
    target_name: str = "本人"
    target_aliases: list[str] = Field(default_factory=list)
    # General twin: other speakers' names in chats and interviews are replaced by stable codes at import.
    pseudonymize_others: bool = True
    max_workers: int = 4
    llm: LLMSettings = Field(default_factory=LLMSettings)
    chat_llm: LLMSettings | None = None
    # ``[llm_fallback]``: another endpoint that answers for ``llm`` and ``chat_llm`` while theirs is unavailable
    # (quota spent, unreachable, key refused); see ``FallbackLLM``. Only the web service and API use it, so a
    # benchmark run from the CLI never mixes in another model's answers.
    llm_fallback: LLMSettings | None = None
    # Evaluation judges (``[[judges]]`` tables). Empty: the main ``llm`` judges. Use 2-3 models of families
    # other than the twin's, since a judge tends to prefer output resembling its own.
    judges: list[LLMSettings] = Field(default_factory=list)
    # Evaluation only (``[eval_chat_llm]``): the model the twin answers public benchmarks with, while profiles still
    # build with ``llm``. Benchmarks never use the production ``[chat_llm]``.
    eval_chat_llm: LLMSettings | None = None
    embed: EmbedSettings = Field(default_factory=EmbedSettings)
    pricing: dict[str, Price] = Field(default_factory=dict)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    ops: OpsSettings = Field(default_factory=OpsSettings)
    upgrade: UpgradeSettings = Field(default_factory=UpgradeSettings)
    kernel: KernelSettings = Field(default_factory=KernelSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    asr: ASRSettings = Field(default_factory=ASRSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    avatar: AvatarSettings = Field(default_factory=AvatarSettings)
    media: MediaSettings = Field(default_factory=MediaSettings)
    library: LibrarySettings = Field(default_factory=LibrarySettings)
    video: VideoSettings = Field(default_factory=VideoSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    wecom: WeComSettings = Field(default_factory=WeComSettings)

    @model_validator(mode="after")
    def build_concurrency(self) -> Settings:
        """A memory build sent ``max_workers`` calls at once before it had a setting of its own, and still does unless
        ``[kernel] max_concurrent`` says otherwise."""
        if "max_concurrent" not in self.kernel.model_fields_set:
            self.kernel.max_concurrent = max(1, min(self.max_workers, MAX_BUILD_CONCURRENT))
        return self

    @property
    def effective_chat_llm(self) -> LLMSettings:
        return self.chat_llm if self.chat_llm is not None else self.llm

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
            "llm": settings.llm.model_dump(mode="json", exclude={"base_url", "api_key_env", "max_concurrent"}),
            "judges": [{"id": judge_id, "effort": effort} for judge_id, effort in judges],
            "chat_llm": {
                **settings.effective_chat_llm.model_dump(
                    mode="json", exclude={"base_url", "api_key_env", "max_concurrent"}
                ),
                "name": llm.name,
            },
            "judge_reasoning_effort": [judge.reasoning_effort for judge in settings.judges],
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
    if settings.tts.voice_dir is not None:
        settings.tts.voice_dir = settings.tts.voice_dir.expanduser()
        if not settings.tts.voice_dir.is_absolute():
            settings.tts.voice_dir = path.parent / settings.tts.voice_dir
    for key_env in [
        settings.llm.api_key_env,
        settings.effective_chat_llm.api_key_env,
        *([settings.llm_fallback.api_key_env] if settings.llm_fallback is not None else []),
        settings.embed.api_key_env,
        settings.tts.api_key_env,
        settings.asr.api_key_env,
        settings.search.api_key_env,
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
            reasoning_effort=s.reasoning_effort,
            extra_body=s.extra_body,
        )
    return ClaudeCLILLM(model=s.model or CLAUDE_DEFAULT_MODEL)


def with_fallback(llm: LLM, settings: Settings) -> LLM:
    """``llm``, answered by ``[llm_fallback]`` while it is unavailable, when one is configured."""
    fallback = settings.llm_fallback
    if fallback is None:
        return llm
    # Read at every call: the section is the one an administrator's change is written into.
    return FallbackLLM(llm, make_llm(fallback, "llm_fallback"), concurrent=lambda: fallback.max_concurrent)


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
        streaming=s.streaming,
        timeout=s.timeout,
        max_retries=s.max_retries,
    )


def make_video_synthesizer(settings: Settings) -> VideoSynthesizer | None:
    """Lazy presentation factory; no remote work is performed during construction."""
    if settings.video.provider == "none":
        return None
    from .media.video import RemoteVideo

    video = settings.video
    assert video.command is not None
    from .assets import AssetStore

    assets = AssetStore(settings.db_path)
    portrait, voice_ref = assets.path("portrait"), assets.path("voice")
    if video.require_assets and (portrait is None or voice_ref is None):
        from .media.tts import MediaUnavailable

        raise MediaUnavailable("先在「关于你」上传形象和声音")
    return RemoteVideo(
        portrait=portrait,
        voice_ref=voice_ref,
        host=video.host,
        command=video.command,
        timeout_s=video.timeout_s,
        max_rounds=video.max_rounds,
        max_cer=video.max_cer,
        pause_s=video.pause_s,
    )


def make_recognizer(s: ASRSettings) -> SpeechRecognizer:
    """Construct an HTTP recognizer without an implicit public endpoint."""
    if s.provider == "command":
        raise ValueError("命令语音识别用于音视频记忆，语音评测请配置 HTTP 识别服务")
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
