"""Enforce media boundaries by inspecting AST imports without importing application modules."""

from __future__ import annotations

import ast
import sys
from importlib.util import resolve_name
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "twin"
MEDIA_ROOT = PACKAGE_ROOT / "media"


def _imports(source: str, package: str) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module or ""
            targets.add(base)
            if base == "twin" or base.startswith("twin."):
                for alias in node.names:
                    candidate = f"{base}.{alias.name}"
                    path = PACKAGE_ROOT.joinpath(*candidate.split(".")[1:])
                    if path.with_suffix(".py").is_file() or (path / "__init__.py").is_file():
                        targets.add(candidate)
    return targets


def _upstream(target: str) -> bool:
    return any(target == root or target.startswith(root + ".") for root in ("twin.persona",))


@pytest.mark.parametrize("path", [*sorted(MEDIA_ROOT.rglob("*.py")), PACKAGE_ROOT / "web" / "media.py"])
def test_only_adapters_import_runtime_types(path: Path) -> None:
    package = "twin.media" if path.is_relative_to(MEDIA_ROOT) else "twin.web"
    if path.name == "__init__.py":
        package = "twin." + ".".join(path.parent.relative_to(PACKAGE_ROOT).parts)
    upstream = {target for target in _imports(path.read_text(encoding="utf-8"), package) if _upstream(target)}
    if path != MEDIA_ROOT / "adapters.py":
        assert not upstream, f"{path.relative_to(PACKAGE_ROOT)} imports upstream modules: {sorted(upstream)}"


def test_script_imports_only_boundary_contract_and_util() -> None:
    targets = _imports((MEDIA_ROOT / "script.py").read_text(encoding="utf-8"), "twin.media")
    assert targets <= {"__future__", "twin.media.schema", "twin.util"}, targets


def test_schema_imports_only_stdlib_pydantic_and_util() -> None:
    targets = _imports((MEDIA_ROOT / "schema.py").read_text(encoding="utf-8"), "twin.media")
    for target in targets:
        if target.startswith("twin"):
            assert target == "twin.util", target
        else:
            assert target.split(".")[0] in sys.stdlib_module_names | {"pydantic"}, target


def test_tts_imports_only_low_level_contract_transport_and_util() -> None:
    targets = _imports((MEDIA_ROOT / "tts.py").read_text(encoding="utf-8"), "twin.media")
    for target in targets:
        if target.startswith("twin"):
            assert target in {"twin.media.schema", "twin.util"}, target
        else:
            assert target.split(".")[0] in sys.stdlib_module_names | {"httpx"}, target


def test_asr_imports_only_low_level_contract_transport_errors_and_util() -> None:
    targets = _imports((MEDIA_ROOT / "asr.py").read_text(encoding="utf-8"), "twin.media")
    for target in targets:
        if target.startswith("twin"):
            assert target in {"twin.media.schema", "twin.media.tts", "twin.util"}, target
        else:
            assert target.split(".")[0] in sys.stdlib_module_names | {"httpx"}, target


def test_check_imports_only_media_util_and_config() -> None:
    targets = _imports((MEDIA_ROOT / "check.py").read_text(encoding="utf-8"), "twin.media")
    for target in targets:
        if target.startswith("twin"):
            assert target.startswith("twin.media.") or target in {
                "twin.util",
                "twin.config",
            }, target
        else:
            assert target.split(".")[0] in sys.stdlib_module_names, target


def test_speech_text_imports_only_stdlib_contract_and_util() -> None:
    targets = _imports((MEDIA_ROOT / "speech_text.py").read_text(encoding="utf-8"), "twin.media")
    for target in targets:
        if target.startswith("twin"):
            assert target in {"twin.media.schema", "twin.util"}, target
        else:
            assert target.split(".")[0] in sys.stdlib_module_names, target


def test_lipsync_imports_only_stdlib_contract_and_util() -> None:
    targets = _imports((MEDIA_ROOT / "lipsync.py").read_text(encoding="utf-8"), "twin.media")
    for target in targets:
        if target.startswith("twin"):
            assert target in {"twin.media.schema", "twin.util"}, target
        else:
            assert target.split(".")[0] in sys.stdlib_module_names, target


def test_render_imports_only_contract_protocol_speech_text_lipsync_and_util() -> None:
    targets = _imports((MEDIA_ROOT / "render.py").read_text(encoding="utf-8"), "twin.media")
    for target in targets:
        if target.startswith("twin"):
            assert target in {
                "twin.media.schema",
                "twin.media.tts",
                "twin.media.speech_text",
                "twin.media.lipsync",
                "twin.util",
            }, target
        else:
            assert target.split(".")[0] in sys.stdlib_module_names, target


def test_clip_imports_only_render_contract_protocol_and_pillow() -> None:
    targets = _imports((MEDIA_ROOT / "clip.py").read_text(encoding="utf-8"), "twin.media")
    for target in targets:
        if target.startswith("twin"):
            assert target in {"twin.media.render", "twin.media.schema", "twin.media.tts"}, target
        else:
            assert target.split(".")[0] in sys.stdlib_module_names | {"PIL"}, target


def test_video_imports_only_media_contract_helpers_and_pillow() -> None:
    targets = _imports((MEDIA_ROOT / "video.py").read_text(encoding="utf-8"), "twin.media")
    for target in targets:
        if target.startswith("twin"):
            assert target in {"twin.media.schema", "twin.media.tts", "twin.media.clip"}, target
        else:
            assert target.split(".")[0] in sys.stdlib_module_names | {"PIL", "pydantic"}, target


def test_config_video_import_is_only_type_checking_or_lazy_factory() -> None:
    tree = ast.parse((PACKAGE_ROOT / "config.py").read_text(encoding="utf-8"))
    for statement in tree.body:
        imports = [
            node for node in ast.walk(statement) if isinstance(node, ast.ImportFrom) and node.module == "media.video"
        ]
        if imports:
            assert (isinstance(statement, ast.FunctionDef) and statement.name == "make_video_synthesizer") or (
                isinstance(statement, ast.If)
                and isinstance(statement.test, ast.Name)
                and statement.test.id == "TYPE_CHECKING"
            )


@pytest.mark.parametrize(
    "source",
    [
        "import twin.persona.schema as runtime",
        "from ..persona.schema import ChatReply as Answer",
        "from .. import persona",
        "import twin.persona.schema as runtime",
        "from ..persona import schema",
        "from twin import persona",
    ],
)
def test_ast_guard_recognises_import_forms(source: str) -> None:
    assert any(_upstream(target) for target in _imports(source, "twin.media"))
