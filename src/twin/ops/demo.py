"""Repository-only fictional demo import, using the web persona registry."""

from __future__ import annotations

import datetime as dt
import json
import secrets
from pathlib import Path

from ..config import Settings
from ..persona.sources import parse_source
from ..persona.store import PersonaStore, stored_identity
from ..web.jobs import JobManager, describe_error
from ..web.personas import Personas

DEMO_NAME = "示例·林舟"
DEMO_DIRECTORY = Path(__file__).resolve().parents[3] / "examples" / "demo"
DEMO_FILES = (
    "2026-01-05-笔记.md",
    "2026-01-06-聊天.csv",
    "2026-01-07-聊天.txt",
    "2026-01-08-访谈.txt",
    "2026-01-09-短文.md",
)


def seed_demo(settings: Settings, *, force: bool = False) -> tuple[str, int]:
    paths = [DEMO_DIRECTORY / name for name in DEMO_FILES]
    if any(not path.is_file() for path in paths):
        raise ValueError("找不到 examples/demo 示例资料；请在完整 git 仓库中运行 uv run twin demo seed")
    registry = Personas(settings, JobManager(settings.max_workers, describe_error))
    entry = next(
        (
            item
            for item in registry.data["personas"]
            if item["id"] != registry.data["default"]
            and not item.get("deleted_at")
            and (
                item.get("demo") == "linzhou"
                or stored_identity(registry.settings_for(item["id"]).db_path)[0] == DEMO_NAME
            )
        ),
        None,
    )
    if entry is None:
        entry = {
            "id": "p-" + secrets.token_hex(5),
            "owner": None,
            "created_at": dt.datetime.now(dt.UTC).isoformat(),
            "demo": "linzhou",
        }
        registry.data["personas"].append(entry)
    resolved = registry.settings_for(entry["id"]).model_copy(
        update={"target_name": DEMO_NAME, "target_aliases": ["林舟"]}
    )
    parsed = [parse_source(None, path, resolved) for path in paths]
    with PersonaStore(resolved.db_path) as store:
        if not store.get_meta("identity:name"):
            store.set_identity(DEMO_NAME, "", None)
        previous: dict[str, str] = json.loads(store.get_meta("demo:sources") or "{}")
        count = 0
        for source in parsed:
            origin, source_id = source.source.origin, source.source.source_id
            old_id = previous.get(origin)
            if not force and old_id and store.get_source(old_id) is not None:
                continue
            if force and old_id and old_id != source_id:
                store.delete_source(old_id)
            if force or store.get_source(source_id) is None:
                store.put_source(source)
                count += 1
            previous[origin] = source_id
        store.set_meta("demo:sources", json.dumps(previous, ensure_ascii=False))
    entry["demo"] = "linzhou"
    registry.save()
    return str(entry["id"]), count
