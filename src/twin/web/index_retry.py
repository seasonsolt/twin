"""Search vectors a build left out while the embedding service could not be reached, filled in once it answers.

A build does not fail for an unreachable embedding service (``run_persona_build``): the twin answers from its new
memory at once, ranked by keywords alone where vectors are missing. Every few minutes this asks each twin whether its
index is behind; when one is, it asks the service for a single vector, and once that works each twin behind updates
its index (``resume_index``, the same as at start-up).
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from ..embed import EmbedError
from .backends import Backends, BackendUnavailable

if TYPE_CHECKING:
    from .personas import Personas

logger = logging.getLogger(__name__)

# How often twins are asked whether their index is behind.
RETRY_SECONDS = 600


class IndexRetry:
    def __init__(self, registry: Personas, backends: Backends) -> None:
        self.registry, self.backends = registry, backends
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None

    def tick(self) -> int:
        """Update the index of every twin whose index is behind, if the embedding service answers; returns how many
        were started."""
        behind = [app for app in list(self.registry.apps.values()) if app.state.index_behind()]
        if not behind:
            return 0
        try:
            self.backends.embedder().embed(["ping"])
        except (EmbedError, BackendUnavailable):
            return 0
        logger.info("向量服务恢复：%d 个分身补齐检索向量", len(behind))
        for app in behind:
            app.state.resume_index()
        return len(behind)

    def _loop(self) -> None:
        while not self.stopping.wait(RETRY_SECONDS):
            try:
                self.tick()
            except Exception:
                logger.warning("补齐检索向量出错", exc_info=True)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name="index-retry", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(15)
