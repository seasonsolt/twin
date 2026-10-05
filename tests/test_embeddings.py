from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import numpy as np
import openai
import pytest
from pydantic import ValidationError

from twin.config import EmbedSettings, make_embedder
from twin.embed import (
    MAX_BATCH_CHARS,
    EmbedError,
    HashingEmbedder,
    OpenAICompatEmbedder,
    embedder_fingerprint,
)


class StubClient:
    def __init__(self, *responses: Any, base_url: str = "https://vectors.example/v1/") -> None:
        self.base_url = base_url
        self.responses = iter(responses)
        self.calls: list[dict[str, Any]] = []
        self.embeddings = self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def response(*rows: tuple[Any, Any]) -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(index=index, embedding=values) for index, values in rows])


CLOUDFLARE_MODEL = "@cf/baai/bge-m3"
CLOUDFLARE_BASE_URL = "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1"


@pytest.fixture
def cloudflare_payload() -> dict[str, Any]:
    """Offline shape fixture for Cloudflare's documented OpenAI-compatible /v1/embeddings:
    https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/

    The page specifies OpenAI SDK compatibility, not a literal response JSON. This fixture uses that
    contract (data entries with index/embedding/object), NOT the native /ai/run result.data matrix.
    Metadata and short vectors are synthetic; this is not a captured live Cloudflare response.
    """
    payload: dict[str, Any] = json.loads(
        """{
            "object": "list",
            "data": [
                {"object": "embedding", "index": 0, "embedding": [3.0, 4.0]},
                {"object": "embedding", "index": 1, "embedding": [0.0, 5.0]}
            ],
            "model": "@cf/baai/bge-m3",
            "usage": {"prompt_tokens": 2, "total_tokens": 2}
        }"""
    )
    return payload


def cloudflare_response(payload: dict[str, Any]) -> SimpleNamespace:
    # Replay the JSON as attribute-bearing SDK response objects at the existing client injection seam.
    return SimpleNamespace(**{**payload, "data": [SimpleNamespace(**row) for row in payload["data"]]})


@pytest.mark.parametrize("out_of_order", [False, True], ids=["normal", "out-of-order"])
def test_cloudflare_response_preserves_order_and_normalises(
    cloudflare_payload: dict[str, Any], out_of_order: bool
) -> None:
    if out_of_order:
        cloudflare_payload["data"].reverse()
    client = StubClient(cloudflare_response(cloudflare_payload), base_url=CLOUDFLARE_BASE_URL)
    embedder = OpenAICompatEmbedder(
        CLOUDFLARE_MODEL, base_url=CLOUDFLARE_BASE_URL, api_key_env="TWIN_EMBED_KEY", client=client
    )

    vectors = embedder.embed(["合成甲", "合成乙"])

    assert vectors.shape == (2, 2)
    assert vectors.dtype == np.float32
    np.testing.assert_allclose(vectors, [[0.6, 0.8], [0, 1]], atol=1e-7)
    assert client.calls == [{"model": CLOUDFLARE_MODEL, "input": ["合成甲", "合成乙"]}]


@pytest.mark.parametrize("missing", ["row", "field", "null", "empty"])
def test_cloudflare_missing_vector_is_rejected(cloudflare_payload: dict[str, Any], missing: str) -> None:
    if missing == "row":
        cloudflare_payload["data"].pop()
    elif missing == "field":
        del cloudflare_payload["data"][1]["embedding"]
    else:
        cloudflare_payload["data"][1]["embedding"] = None if missing == "null" else []
    client = StubClient(cloudflare_response(cloudflare_payload), base_url=CLOUDFLARE_BASE_URL)
    embedder = OpenAICompatEmbedder(CLOUDFLARE_MODEL, client=client)

    with pytest.raises(EmbedError, match="invalid embedding response"):
        embedder.embed(["合成甲", "合成乙"])
    assert len(client.calls) == 1


def test_cloudflare_dimensions_must_match_across_batches(cloudflare_payload: dict[str, Any]) -> None:
    first = deepcopy(cloudflare_payload)
    first["data"] = first["data"][:1]
    second = deepcopy(first)
    second["data"][0]["embedding"] = [0.0, 1.0, 0.0]
    client = StubClient(cloudflare_response(first), cloudflare_response(second), base_url=CLOUDFLARE_BASE_URL)
    embedder = OpenAICompatEmbedder(CLOUDFLARE_MODEL, batch_size=1, client=client)

    with pytest.raises(EmbedError, match="dimensions differ between rows or batches"):
        embedder.embed(["合成甲", "合成乙"])
    assert client.calls == [
        {"model": CLOUDFLARE_MODEL, "input": ["合成甲"]},
        {"model": CLOUDFLARE_MODEL, "input": ["合成乙"]},
    ]


def test_cloudflare_batch_size_limits_requests_and_resets_indices(cloudflare_payload: dict[str, Any]) -> None:
    last = deepcopy(cloudflare_payload)
    last["data"] = last["data"][:1]
    client = StubClient(
        cloudflare_response(cloudflare_payload),
        cloudflare_response(cloudflare_payload),
        cloudflare_response(last),
        base_url=CLOUDFLARE_BASE_URL,
    )
    embedder = OpenAICompatEmbedder(CLOUDFLARE_MODEL, batch_size=2, client=client)

    vectors = embedder.embed(["合成甲", "合成乙", "合成丙", "合成丁", "合成戊"])

    np.testing.assert_allclose(vectors, [[0.6, 0.8], [0, 1], [0.6, 0.8], [0, 1], [0.6, 0.8]], atol=1e-7)
    assert vectors.dtype == np.float32
    assert client.calls == [
        {"model": CLOUDFLARE_MODEL, "input": ["合成甲", "合成乙"]},
        {"model": CLOUDFLARE_MODEL, "input": ["合成丙", "合成丁"]},
        {"model": CLOUDFLARE_MODEL, "input": ["合成戊"]},
    ]


def test_batches_preserve_input_order_and_normalise_provider_vectors() -> None:
    client = StubClient(response((1, [0, 5]), (0, [3, 4])), response((0, [-7, 0])))
    # The historical positional signature, including the injected client, remains valid.
    embedder = OpenAICompatEmbedder("model-a", None, "UNUSED", 2, 0.82, client)

    vectors = embedder.embed(["甲", "乙", "丙"])

    np.testing.assert_allclose(vectors, [[0.6, 0.8], [0, 1], [-1, 0]], atol=1e-7)
    assert vectors.dtype == np.float32
    assert client.calls == [
        {"model": "model-a", "input": ["甲", "乙"]},
        {"model": "model-a", "input": ["丙"]},
    ]


def test_batches_also_close_at_the_padded_character_budget() -> None:
    third = "长" * (MAX_BATCH_CHARS // 3)
    client = StubClient(response((0, [1, 0]), (1, [0, 1])), response((0, [0, 1]), (1, [1, 1])), response((0, [1, 0])))
    embedder = OpenAICompatEmbedder("model-a", batch_size=10, client=client)

    # Short texts are padded to the longest one in the request: "短" + 2 x third would cost 3 x third + 3.
    assert embedder.embed(["短", third + "长", third, third, "长" * (MAX_BATCH_CHARS + 1)]).shape == (5, 2)
    assert [len(c["input"]) for c in client.calls] == [2, 2, 1]  # an oversized text still goes, alone


@pytest.mark.parametrize(
    "bad_response",
    [
        response((0, [1, 0])),
        response((0, [1, 0]), (0, [0, 1])),
        response((0, [1, 0]), (2, [0, 1])),
        response((-1, [1, 0]), (1, [0, 1])),
        response((0, [1, 0]), (True, [0, 1])),
        response((0, [1, 0]), (1.0, [0, 1])),
        response((0, [1, 0]), (1, [0, 1]), (2, [1, 1])),
        SimpleNamespace(data=[SimpleNamespace(embedding=[1, 0]), SimpleNamespace(index=1, embedding=[0, 1])]),
        SimpleNamespace(data=None),
        SimpleNamespace(),
    ],
    ids=["missing", "duplicate", "too-large", "negative", "bool", "float", "extra", "no-index", "null", "no-data"],
)
def test_malformed_response_cannot_silently_misalign_documents(bad_response: Any) -> None:
    embedder = OpenAICompatEmbedder("model-a", client=StubClient(bad_response))

    with pytest.raises(EmbedError, match="invalid embedding response"):
        embedder.embed(["甲", "乙"])


@pytest.mark.parametrize(
    "values",
    [[], [0, 0], [float("nan"), 1], [float("inf"), 1], [float("-inf"), 1], ["1", 2], [True, 1], [[1], [2]], None],
    ids=["empty", "zero", "nan", "inf", "negative-inf", "string", "bool", "nested", "null"],
)
def test_invalid_vector_values_raise_embed_error(values: Any) -> None:
    embedder = OpenAICompatEmbedder("model-a", client=StubClient(response((0, values))))

    with pytest.raises(EmbedError, match="invalid embedding response"):
        embedder.embed(["甲"])


@pytest.mark.parametrize("batch_size", [1, 2])
def test_dimension_drift_is_rejected_within_and_between_batches(batch_size: int) -> None:
    rows = ((0, [1, 0]), (1, [0, 1, 0]))
    replies = (response(*rows),) if batch_size == 2 else (response(rows[0]), response((0, rows[1][1])))
    embedder = OpenAICompatEmbedder("model-a", batch_size=batch_size, client=StubClient(*replies))

    with pytest.raises(EmbedError, match="dimensions differ"):
        embedder.embed(["甲", "乙"])


def test_finite_extreme_values_still_produce_unit_vectors() -> None:
    client = StubClient(response((0, [1e300, 1e300]), (1, [1e-300, -1e-300])))
    vectors = OpenAICompatEmbedder("model-a", client=client).embed(["甲", "乙"])

    assert np.isfinite(vectors).all()
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), [1, 1], atol=1e-7)


def test_provider_failure_has_a_consistent_public_error_type() -> None:
    error = openai.OpenAIError("service unavailable")
    embedder = OpenAICompatEmbedder("model-a", client=StubClient(error))

    with pytest.raises(EmbedError, match="OpenAIError") as caught:
        embedder.embed(["甲"])

    assert caught.value.__cause__ is error


def test_sdk_parse_failure_is_also_an_embed_error() -> None:
    embedder = OpenAICompatEmbedder("model-a", client=StubClient(ValueError("malformed provider payload")))

    with pytest.raises(EmbedError, match="invalid embedding response"):
        embedder.embed(["甲"])


def test_empty_input_does_not_contact_provider() -> None:
    client = StubClient()
    result = OpenAICompatEmbedder("model-a", client=client).embed([])

    assert result.shape == (0, 0)
    assert result.dtype == np.float32
    assert client.calls == []


@pytest.mark.parametrize("batch_size", [0, -1, True, 1.5])
def test_direct_construction_rejects_invalid_batch_size(batch_size: Any) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        OpenAICompatEmbedder("model-a", batch_size=batch_size, client=StubClient())


@pytest.mark.parametrize(
    "fields",
    [
        {"batch_size": 0},
        {"batch_size": -1},
        {"timeout": 0},
        {"timeout": -1},
        {"timeout": float("inf")},
        {"max_retries": -1},
        {"cluster_threshold": 0},
        {"cluster_threshold": -0.1},
        {"cluster_threshold": 1.1},
        {"cluster_threshold": float("nan")},
    ],
)
def test_embedding_settings_reject_unusable_configuration(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EmbedSettings(**fields)


def test_threshold_boundaries_and_request_defaults() -> None:
    assert EmbedSettings(cluster_threshold=1).cluster_threshold == 1
    settings = EmbedSettings()
    assert (settings.batch_size, settings.timeout, settings.max_retries) == (32, 60, 2)


def test_factory_passes_request_configuration_to_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    options: dict[str, Any] = {}
    client = StubClient()

    def construct(**kwargs: Any) -> StubClient:
        options.update(kwargs)
        return client

    monkeypatch.setattr(openai, "OpenAI", construct)
    embedder = make_embedder(
        EmbedSettings(
            provider="openai_compat",
            base_url="https://configured.example/v1",
            model="model-a",
            batch_size=7,
            timeout=12.5,
            max_retries=0,
        )
    )

    assert isinstance(embedder, OpenAICompatEmbedder)
    assert embedder.batch_size == 7
    assert options["timeout"] == 12.5
    assert options["max_retries"] == 0
    assert options["base_url"] == "https://configured.example/v1"
    assert embedder.base_url == client.base_url


def test_hashing_fingerprint_tracks_vector_space_but_not_threshold() -> None:
    original = embedder_fingerprint(HashingEmbedder(dim=8, ngrams=(1, 2)))

    assert original == embedder_fingerprint(HashingEmbedder(dim=8, ngrams=(1, 2), cluster_threshold=0.9))
    assert original != embedder_fingerprint(HashingEmbedder(dim=9, ngrams=(1, 2)))
    assert original != embedder_fingerprint(HashingEmbedder(dim=8, ngrams=(2, 3)))


def test_remote_fingerprint_tracks_actual_sdk_endpoint_and_model_without_secrets() -> None:
    def fingerprint(model: str, endpoint: str, **kwargs: Any) -> str:
        return embedder_fingerprint(
            OpenAICompatEmbedder(
                model,
                base_url="https://ignored.example/v1",
                client=StubClient(base_url=endpoint),
                **kwargs,
            )
        )

    original = fingerprint("model-a", "https://user:secret@VECTORS.example:443/v1/?key=secret#secret")

    assert original == fingerprint(
        "model-a", "https://vectors.example//v1/./", cluster_threshold=0.9, batch_size=9, timeout=99, max_retries=0
    )
    assert original != fingerprint("model-b", "https://vectors.example/v1")
    assert original != fingerprint("model-a", "https://other.example/v1")
    assert original != fingerprint("model-a", "https://vectors.example/another/v1")
    assert len(original) == 64
    assert "secret" not in original and "example" not in original and "model" not in original


def test_test_double_fingerprint_falls_back_to_name() -> None:
    assert embedder_fingerprint(SimpleNamespace(name="fake-a")) == embedder_fingerprint(SimpleNamespace(name="fake-a"))
    assert embedder_fingerprint(SimpleNamespace(name="fake-a")) != embedder_fingerprint(SimpleNamespace(name="fake-b"))


def test_observation_wrapper_preserves_the_inner_vector_space() -> None:
    inner = HashingEmbedder(dim=8, ngrams=(1, 2))
    wrapper = SimpleNamespace(name=inner.name, inner=inner, embed=inner.embed)

    assert embedder_fingerprint(wrapper) == embedder_fingerprint(inner)
