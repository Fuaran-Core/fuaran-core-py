"""The package's own contract: what it says about itself is true, and it is standard library only."""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import fuaran_core

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "fuaran_core"


def test_the_declared_version_matches_the_package() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        declared = tomllib.load(handle)["project"]["version"]
    assert declared == fuaran_core.__version__


def test_the_public_modules_are_the_spine() -> None:
    assert fuaran_core.__all__ == [
        "address",
        "chain",
        "dag",
        "decimal",
        "decode",
        "json",
        "ops",
        "tree",
    ]


def _imports(module: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


def test_the_runtime_is_standard_library_only() -> None:
    """Every module under ``src/fuaran_core`` imports the standard library and this package,
    and nothing else: a host embeds the spine where no third-party package can be installed
    (a browser runtime, a vendored copy), so the dependency set is held by a test."""
    stdlib = sys.stdlib_module_names
    for module in PACKAGE.glob("*.py"):
        foreign = {
            name for name in _imports(module) if name not in stdlib and name != "fuaran_core"
        }
        assert not foreign, f"{module.name} imports outside the standard library: {sorted(foreign)}"
