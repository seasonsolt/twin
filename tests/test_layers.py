"""Enforce the target layers defined in docs/ARCHITECTURE.md."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "twin"
LAYERS: dict[str, int] = {
    "": 9,
    "util": 0,
    "usage": 0,
    "assets": 0,
    "evals": 8,
    "evals.harness": 8,
    "evals.stats": 0,
    "evals.schema": 1,
    "media": 1,
    "media.schema": 1,
    "media.tts": 2,
    "media.asr": 2,
    "media.ingest": 7,
    "media.claim": 7,
    "media.check": 8,
    "media.script": 7,
    "media.adapters": 7,
    "media.render": 7,
    "media.stream": 7,
    "media.clip": 7,
    "media.video": 7,
    "media.lipsync": 7,
    "media.speech_text": 7,
    "web.media": 9,
    "web.assets": 9,
    "web.uploads": 9,
    "web.claims": 9,
    "identity": 1,
    "persona": 1,
    "persona.dimensions": 1,
    "persona.schema": 1,
    "persona.items": 1,
    "llm": 2,
    "embed": 2,
    "config": 2,
    "persona.store": 3,
    "persona.sources": 4,
    "persona.text": 4,
    "persona.quotes": 4,
    "persona.questionnaire": 4,
    "persona.profile": 5,
    "persona.coverage": 5,
    "persona.chat": 6,
    "evals.provenance": 8,
    "evals.personal": 8,
    "service": 7,
    "api": 9,
    "mcp_server": 9,
    "cli": 9,
    "egress": 9,
    "web": 9,
    "web.app": 9,
    "web.auth": 9,
    "web.backends": 9,
    "web.jobs": 9,
    "web.persona": 9,
    "web.conversations": 9,
    "web.personas": 9,
    "web.identity": 9,
}


def _module_paths() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        parts = path.relative_to(PACKAGE_ROOT).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules[".".join(parts)] = path
    return modules


def _internal_name(name: str) -> str | None:
    if name == "twin":
        return ""
    if name.startswith("twin."):
        return name.removeprefix("twin.")
    return None


def _import_targets(module: str, path: Path, modules: dict[str, Path]) -> set[str]:
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    qualified_package = "twin" + (f".{package}" if package else "")
    targets: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _internal_name(alias.name)
                if target is not None:
                    targets.add(target)
        elif isinstance(node, ast.ImportFrom):
            name = node.module or ""
            if node.level:
                name = resolve_name("." * node.level + name, qualified_package)
            base = _internal_name(name)
            if base is None:
                continue
            for alias in node.names:
                candidate = f"{base}.{alias.name}" if base else alias.name
                targets.add(candidate if candidate in modules else base)
    return targets


def _import_graph(modules: dict[str, Path]) -> dict[str, set[str]]:
    packages = {module for module, path in modules.items() if path.name == "__init__.py"}
    graph: dict[str, set[str]] = {}
    for source, path in modules.items():
        graph[source] = {
            target
            for target in _import_targets(source, path, modules)
            if not (target in packages and source != target and (not target or source.startswith(f"{target}.")))
        }
    return graph


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visited: set[str] = set()
    active: dict[str, int] = {}
    stack: list[str] = []

    def visit(module: str) -> list[str] | None:
        if module in active:
            return [*stack[active[module] :], module]
        if module in visited:
            return None
        active[module] = len(stack)
        stack.append(module)
        for target in sorted(graph.get(module, set())):
            cycle = visit(target)
            if cycle is not None:
                return cycle
        stack.pop()
        del active[module]
        visited.add(module)
        return None

    for module in sorted(graph):
        cycle = visit(module)
        if cycle is not None:
            return cycle
    return None


def _display_name(module: str) -> str:
    return module or "twin"


def test_every_module_has_a_layer() -> None:
    modules = _module_paths()
    unregistered = sorted(modules.keys() - LAYERS.keys())
    stale = sorted(LAYERS.keys() - modules.keys())
    failures: list[str] = []
    if unregistered:
        failures.append("Unregistered modules: " + ", ".join(map(_display_name, unregistered)))
    if stale:
        failures.append("Stale layer entries (missing files): " + ", ".join(map(_display_name, stale)))
    if failures:
        pytest.fail("\n".join(failures), pytrace=False)


def test_imports_point_down() -> None:
    graph = _import_graph(_module_paths())
    violations = [
        f"{_display_name(source)} ({LAYERS[source]}) -> {_display_name(target)} ({LAYERS[target]})"
        for source in sorted(graph)
        for target in sorted(graph[source])
        if source in LAYERS
        and target in LAYERS
        and LAYERS[target] > LAYERS[source]
        # Configuration is the sole, lazy construction entry point for presentation backends.
        and (source, target) != ("config", "media.video")
    ]
    if violations:
        pytest.fail("Upward imports:\n" + "\n".join(violations), pytrace=False)


def test_no_import_cycles() -> None:
    cycle = _find_cycle(_import_graph(_module_paths()))
    if cycle is not None:
        pytest.fail("Import cycle: " + " -> ".join(map(_display_name, cycle)), pytrace=False)
