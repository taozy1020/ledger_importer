"""The dependency rules, checked instead of documented.

A layer may only import from itself and the layers listed below it. This is
what keeps a part replaceable: if `advice` cannot see `semantic`, then swapping
the model out cannot break the memory, and neither can be tested through the
other by accident.
"""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "bean_import"
PACKAGE = "bean_import"

ALLOWED: dict[str, set[str]] = {
    "core": {"core"},
    "clock": {"core", "clock"},
    "config": {"core", "config"},
    "sources": {"core", "config", "sources"},
    "journal": {"core", "journal"},
    "advice": {"core", "advice"},
    "learning": {"core", "learning"},
    "semantic": {"core", "semantic"},
    "csv_demo": {"core", "csv_demo"},
    "app": {
        "advice",
        "app",
        "clock",
        "config",
        "core",
        "journal",
        "learning",
        "semantic",
        "sources",
    },
}


def modules() -> list[Path]:
    return sorted(path for path in SOURCE.rglob("*.py"))


def layer_of(path: Path) -> str:
    relative = path.relative_to(SOURCE)
    return relative.parts[0] if len(relative.parts) > 1 else relative.stem


def imports(tree: ast.Module, *, top_level_only: bool = False) -> set[str]:
    """Every `bean_import` layer a module reaches for."""

    found: set[str] = set()
    nodes = tree.body if top_level_only else list(ast.walk(tree))
    for node in nodes:
        if isinstance(node, ast.ImportFrom) and node.module:
            name = node.module
        elif isinstance(node, ast.Import):
            name = node.names[0].name
        else:
            continue
        parts = name.split(".")
        if parts[0] == PACKAGE and len(parts) > 1:
            found.add(parts[1])
    return found


def test_every_module_belongs_to_a_declared_layer() -> None:
    layers = {layer_of(path) for path in modules()} - {"__init__"}

    assert layers <= set(ALLOWED), sorted(layers - set(ALLOWED))


def test_no_layer_reaches_past_the_ones_below_it() -> None:
    violations: list[str] = []
    for path in modules():
        layer = layer_of(path)
        permitted = ALLOWED.get(layer, set())
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for target in imports(tree) - permitted:
            violations.append(f"{path.relative_to(SOURCE)} imports {target}")

    assert violations == []


def test_the_core_never_imports_an_adapter_at_all() -> None:
    for path in modules():
        if layer_of(path) != "core":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert imports(tree) <= {"core"}, path.name


def test_only_the_composition_root_mentions_the_model_and_only_lazily() -> None:
    """Deleting `semantic/` must leave milestone 1 importable."""

    eager: list[str] = []
    for path in modules():
        layer = layer_of(path)
        if layer == "semantic":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if "semantic" in imports(tree, top_level_only=True):
            eager.append(str(path.relative_to(SOURCE)))

    assert eager == []
