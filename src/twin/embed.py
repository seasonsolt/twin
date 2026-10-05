"""Text embedders. All return L2-normalised float32 matrices of shape (n, dim)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from numbers import Real
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from .usage import canonical_endpoint, request, tracked
from .util import key_from_env

Matrix = NDArray[np.float32]


class EmbedError(RuntimeError):
    """The embedding service failed or returned invalid vectors."""


class Embedder(Protocol):
    name: str
    cluster_threshold: float

    def embed(self, texts: list[str]) -> Matrix: ...


def _normalise(m: NDArray[np.floating[Any]]) -> Matrix:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    out: Matrix = (m / norms).astype(np.float32)
    return out


_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)


class HashingEmbedder:
    """Model-free character n-gram embedder. Works offline; good enough for lexical similarity in Chinese.

    Use a real embedding model (bge-m3 / Qwen3-Embedding behind an OpenAI-compatible endpoint) for
    anything beyond tests and demos.
    """

    def __init__(self, dim: int = 4096, ngrams: tuple[int, ...] = (1, 2, 3), cluster_threshold: float = 0.6):
        self.dim = dim
        self.ngrams = ngrams
        self.cluster_threshold = cluster_threshold
        self.name = f"hashing:{dim}"

    def _bucket(self, gram: str) -> int:
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "little") % self.dim

    @tracked("hashing", zero=True)
    def embed(self, texts: list[str]) -> Matrix:
        m = np.zeros((len(texts), self.dim), dtype=np.float64)
        for row, text in enumerate(texts):
            s = _PUNCT.sub("", text.lower())
            counts: dict[int, int] = {}
            for n in self.ngrams:
                for i in range(len(s) - n + 1):
                    b = self._bucket(s[i : i + n])
                    counts[b] = counts.get(b, 0) + 1
            for b, c in counts.items():
                m[row, b] = 1.0 + math.log(c)
        return _normalise(m)


MAX_BATCH_CHARS = 30_000


class OpenAICompatEmbedder:
    """Embeddings via any OpenAI-compatible /v1/embeddings endpoint (TEI, Infinity, vLLM, cloud APIs)."""

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        batch_size: int = 32,
        cluster_threshold: float = 0.82,
        client: Any | None = None,
        *,
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        import openai

        key_from_env(api_key_env)
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        self.model = model
        self.max_retries = max_retries
        self.batch_size = batch_size
        self.cluster_threshold = cluster_threshold
        self.name = f"openai_compat:{model}"
        if client is not None and callable(getattr(client, "with_options", None)):
            client = client.with_options(max_retries=0)
        self._client = (
            client
            if client is not None
            else openai.OpenAI(
                base_url=base_url,
                api_key=key_from_env(api_key_env) or "EMPTY",
                timeout=timeout,
                max_retries=0,
            )
        )
        self.base_url = str(getattr(self._client, "base_url", base_url or os.environ.get("OPENAI_BASE_URL", "")))

    def _validate_batch(self, data: Any, count: int, dimension: int | None) -> Matrix:
        if not isinstance(data, list) or len(data) != count:
            raise ValueError("response row count does not match input")
        rows: dict[int, list[float] | tuple[float, ...]] = {}
        for entry in data:
            index = entry.index
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count or index in rows:
                raise ValueError("response indices must be unique integers covering every input")
            values = entry.embedding
            if not isinstance(values, (list, tuple)) or not values:
                raise ValueError("embedding must be a nonempty numeric vector")
            if any(isinstance(value, bool) or not isinstance(value, Real) for value in values):
                raise ValueError("embedding must contain only numbers")
            if dimension is None:
                dimension = len(values)
            if len(values) != dimension:
                raise ValueError("embedding dimensions differ between rows or batches")
            rows[index] = values
        matrix = np.asarray([rows[index] for index in range(count)], dtype=np.float64)
        if not np.isfinite(matrix).all():
            raise ValueError("embedding contains non-finite numbers")
        scales = np.max(np.abs(matrix), axis=1, keepdims=True)
        if (scales == 0).any():
            raise ValueError("embedding has zero norm")
        # Scaling first keeps finite but very large or small provider values normalisable.
        return _normalise(matrix / scales)

    def _batches(self, texts: list[str]) -> list[list[str]]:
        """Requests of at most ``batch_size`` texts whose padded size (count x longest text) stays within
        ``MAX_BATCH_CHARS`` (a text longer than that goes alone): endpoints also cap the tokens of one request and
        count every input at the padded length (Workers AI bge-m3: 60k)."""
        batches: list[list[str]] = []
        current: list[str] = []
        longest = 0
        for text in texts:
            padded = (len(current) + 1) * max(longest, len(text))
            if current and (len(current) == self.batch_size or padded > MAX_BATCH_CHARS):
                batches.append(current)
                current, longest = [], 0
            current.append(text)
            longest = max(longest, len(text))
        batches.append(current)
        return batches

    def embed(self, texts: list[str]) -> Matrix:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        batches: list[Matrix] = []
        dimension: int | None = None
        for batch in self._batches(texts):
            matrix = self._embed_batch(batch, dimension)
            dimension = matrix.shape[1]
            batches.append(matrix)
        return np.concatenate(batches, axis=0)

    @tracked("openai_compat_embed")
    def _embed_batch(self, batch: list[str], dimension: int | None) -> Matrix:
        import openai

        try:
            resp = request(
                lambda: self._client.embeddings.create(model=self.model, input=batch),
                self.max_retries,
                input_estimate=sum(len(text.encode()) for text in batch),
                characters=sum(len(text) for text in batch),
            )
            return self._validate_batch(resp.data, len(batch), dimension)
        except openai.OpenAIError as e:
            raise EmbedError(f"{self.name}: {type(e).__name__}: {e}") from e
        except (AttributeError, TypeError, ValueError, OverflowError) as e:
            raise EmbedError(f"{self.name}: invalid embedding response: {e}") from e


def embedder_fingerprint(embedder: Embedder) -> str:
    """Identify the vector space without exposing endpoint credentials or addresses."""
    seen: set[int] = set()
    while not isinstance(embedder, (HashingEmbedder, OpenAICompatEmbedder)) and id(embedder) not in seen:
        seen.add(id(embedder))
        inner = getattr(embedder, "inner", None)
        if (
            inner is None
            or getattr(inner, "name", None) != embedder.name
            or not callable(getattr(inner, "embed", None))
        ):
            break
        embedder = inner
    identity: dict[str, object]
    if isinstance(embedder, HashingEmbedder):
        identity = {
            "provider": "hashing",
            "algorithm": "blake2b-char-logcount-v1",
            "dim": embedder.dim,
            "ngrams": embedder.ngrams,
        }
    elif isinstance(embedder, OpenAICompatEmbedder):
        identity = {
            "provider": "openai_compat",
            "model": embedder.model,
            "endpoint": canonical_endpoint(embedder.base_url),
        }
    else:
        identity = {"provider": "custom", "name": embedder.name}
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
