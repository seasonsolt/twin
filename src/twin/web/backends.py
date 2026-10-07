from __future__ import annotations

import threading
from collections.abc import Callable

from ..config import Settings, make_embedder, make_llm
from ..embed import Embedder
from ..evals.harness import Judge
from ..llm import LLM

LLMFactory = Callable[[], LLM]
EmbedderFactory = Callable[[], Embedder]


class BackendUnavailable(Exception):
    """The model or embedding backend cannot be constructed from the configuration (answered with 503)."""


class Backends:
    """The LLM, embedder and judging panel, created on first use, so a configuration error only affects the
    endpoints that call a model; browsing keeps working."""

    def __init__(
        self, settings: Settings, llm_factory: LLMFactory | None, embedder_factory: EmbedderFactory | None
    ) -> None:
        self._settings = settings
        self._llm_factory: LLMFactory = llm_factory or (lambda: make_llm(settings.llm))
        self._chat_llm_factory: LLMFactory = llm_factory or (lambda: make_llm(settings.effective_chat_llm, "chat_llm"))
        self._embedder_factory: EmbedderFactory = embedder_factory or (lambda: make_embedder(settings.embed))
        self._lock = threading.Lock()
        self._llm: LLM | None = None
        self._chat_llm: LLM | None = None
        self._embedder: Embedder | None = None
        self._judges: list[Judge] | None = None

    def llm(self) -> LLM:
        with self._lock:
            if self._llm is None:
                try:
                    self._llm = self._llm_factory()
                except Exception as e:
                    raise BackendUnavailable(
                        f"无法初始化大模型后端 {self._settings.llm.provider}：{e}"
                        "（密钥只能通过环境变量提供，见 README 的配置一节）"
                    ) from e
            return self._llm

    def chat_llm(self) -> LLM:
        if self._settings.chat_llm is None:
            return self.llm()
        with self._lock:
            if self._chat_llm is None:
                try:
                    self._chat_llm = self._chat_llm_factory()
                except Exception as e:
                    raise BackendUnavailable(
                        f"无法初始化聊天大模型后端 {self._settings.effective_chat_llm.provider}：{e}"
                        "（密钥只能通过环境变量提供，见 README 的配置一节）"
                    ) from e
            return self._chat_llm

    def embedder(self) -> Embedder:
        with self._lock:
            if self._embedder is None:
                try:
                    self._embedder = self._embedder_factory()
                except Exception as e:
                    raise BackendUnavailable(f"无法初始化向量化后端 {self._settings.embed.provider}：{e}") from e
            return self._embedder

    def judges(self) -> list[Judge]:
        """The ``[[judges]]`` panel; empty when none is configured (the main model then judges)."""
        with self._lock:
            if self._judges is None:
                panel: list[Judge] = []
                for k, judge in enumerate(self._settings.judges, 1):
                    try:
                        backend = make_llm(judge, f"judges #{k}")
                    except Exception as e:
                        raise BackendUnavailable(f"无法初始化第 {k} 个评委（[[judges]]，{judge.provider}）：{e}") from e
                    panel.append(Judge(backend, judge.effort_extract))
                self._judges = panel
            return self._judges

    def describe(self) -> dict[str, dict[str, str | None]]:
        """Backend name or configuration error of the LLM and the embedder, for the status bar."""
        out: dict[str, dict[str, str | None]] = {}
        for key, get in (("llm", self.llm), ("chat_llm", self.chat_llm), ("embed", self.embedder)):
            try:
                out[key] = {"name": get().name, "error": None}
            except BackendUnavailable as e:
                out[key] = {"name": None, "error": str(e)}
        return out
