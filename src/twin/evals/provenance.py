"""Private schema report persistence with endpoint and credential redaction."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from ..config import Settings
from ..usage import active_recorder
from ..util import open_private, private_directory
from .schema import Report


def write_report(path: Path, report: Report, settings: Settings) -> None:
    """Attach usage under metrics (preserving the strict Report contract), then redact runtime secrets."""
    endpoints = [
        settings.llm.base_url,
        settings.effective_chat_llm.base_url,
        settings.embed.base_url,
        *(judge.base_url for judge in settings.judges),
    ]
    names = {
        settings.llm.api_key_env,
        settings.effective_chat_llm.api_key_env,
        settings.embed.api_key_env,
        *(judge.api_key_env for judge in settings.judges),
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    }
    sensitive = {value for name in names if (value := os.environ.get(name))}
    sensitive.update(url for url in endpoints if url)
    if url := os.environ.get("OPENAI_BASE_URL"):
        sensitive.add(url)
        endpoints.append(url)
    for endpoint in endpoints:
        if endpoint:
            parts = urlsplit(endpoint)
            sensitive.update(value for value in (parts.query, parts.username, parts.password) if value)
            sensitive.update(value for _, value in parse_qsl(parts.query) if value)
    recorder = active_recorder()
    payload = report.model_dump(mode="json")
    if recorder is not None:
        payload["metrics"] = {**payload["metrics"], "usage": recorder.summary()}
    pattern = re.compile("|".join(re.escape(secret) for secret in sorted(sensitive, key=len, reverse=True)))

    def redact(value: Any) -> Any:
        # Redact string values, not serialized JSON syntax: even a one-character key must not corrupt numbers.
        if isinstance(value, str):
            return pattern.sub("[redacted]", value) if sensitive else value
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        return value

    text = json.dumps(redact(payload), ensure_ascii=False, indent=2)
    private_directory(path.parent)
    with open_private(path) as stream:
        stream.write(text)
    if recorder is not None:
        recorder.write(path.parent)
