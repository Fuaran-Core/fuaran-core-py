"""The conformance legs certify the spine against the vectors the reference emits, read from a
checkout of Core (Fuaran-Core/fuaran-core) at the commit ``core-pin.json`` names.

The checkout is found at ``FUARAN_CORE_DIR``, or as ``fuaran-core/`` beside this repository or
beside any directory above it (the layout CI checks it out in). It is NOT optional: a suite that
skipped its vectors would read green while certifying nothing, so an absent checkout FAILS every
leg here, naming how to provide it. The oracle process the differential drives is the same: it
is found through ``FUARAN_CORE_ORACLE`` (a command line) or built under the checkout's
``tools/Fuaran.Core.Oracle.Cli/bin/Release``, and a missing oracle fails rather than skips.

Each leg asserts the vector count its family's ``manifest.json`` declares (where the family has
one), and fails on a vector it did not run, so a leg that silently ran nothing cannot pass.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from fuaran_core import json, oracle

ROOT = Path(__file__).resolve().parents[1]


def _is_core(path: Path) -> bool:
    return (path / "conformance" / "apply" / "manifest.json").is_file()


def core_dir() -> Path:
    """The Core checkout, or a failure naming the remedy."""
    env = os.environ.get("FUARAN_CORE_DIR")
    if env:
        path = Path(env)
        if not _is_core(path):
            pytest.fail(
                f"FUARAN_CORE_DIR={env} is not a Core checkout (no conformance/apply/manifest.json)"
            )
        return path
    for ancestor in ROOT.parents:
        candidate = ancestor / "fuaran-core"
        if _is_core(candidate):
            return candidate
    pytest.fail(
        "no Core checkout found: clone https://github.com/Fuaran-Core/fuaran-core beside this repository "
        "(as fuaran-core/), checked out at the commit core-pin.json names, or set FUARAN_CORE_DIR to one"
    )


@pytest.fixture(scope="session")
def core() -> Path:
    return core_dir()


class Vectors:
    """The reference's ``conformance/`` read through the spine's own reader."""

    def __init__(self, core: Path) -> None:
        self.core = core

    def read(self, rel: str) -> json.Value:
        """``conformance/<rel>`` of the checkout, parsed."""
        path = self.core / "conformance" / rel
        return json.parse(path.read_text(encoding="utf-8"))

    def declared(self, directory: str, family: str) -> int:
        """The family row's declared vector count in ``<directory>/manifest.json``."""
        manifest = self.read(f"{directory}/manifest.json")
        for row in arr(manifest, "families"):
            if s(row, "id") == family:
                return int(n(row, "vectors"))
        pytest.fail(f"{directory}/manifest.json declares no {family}")

    def family(self, directory: str, file: str, family: str) -> list[json.Value]:
        """The vectors of a family whose file is under ``directory``, held to the manifest's
        count."""
        doc = self.read(f"{directory}/{file}")
        want = self.declared(directory, family)
        vectors = arr(doc, "vectors")
        assert len(vectors) == want, f"{file}: {len(vectors)} vectors, the manifest declares {want}"
        return vectors


@pytest.fixture(scope="session")
def vectors(core: Path) -> Vectors:
    return Vectors(core)


# ── required-member accessors ────────────────────────────────────────────────────────


def get(v: json.Value, k: str) -> json.Value:
    assert isinstance(v, dict) and k in v, f"missing member '{k}' in {json.render(v)}"
    return v[k]


def has(v: json.Value, k: str) -> bool:
    return isinstance(v, dict) and k in v


def s(v: json.Value, k: str) -> str:
    x = get(v, k)
    assert isinstance(x, str), f"'{k}' is not a string: {json.render(x)}"
    return x


def n(v: json.Value, k: str) -> float:
    x = get(v, k)
    assert isinstance(x, float), f"'{k}' is not a number: {json.render(x)}"
    return x


def arr(v: json.Value, k: str) -> list[json.Value]:
    x = get(v, k)
    assert isinstance(x, list), f"'{k}' is not an array: {json.render(x)}"
    return x


def str_items(v: json.Value, k: str) -> list[str]:
    out = []
    for i, item in enumerate(arr(v, k)):
        assert isinstance(item, str), f"'{k}'[{i}] is not a string"
        out.append(item)
    return out


# ── the oracle ───────────────────────────────────────────────────────────────────────


def oracle_command_line(core: Path) -> str:
    line = os.environ.get("FUARAN_CORE_ORACLE")
    if line:
        return line
    dll = (
        core
        / "tools"
        / "Fuaran.Core.Oracle.Cli"
        / "bin"
        / "Release"
        / "net10.0"
        / "fuaran-core-oracle.dll"
    )
    if not dll.is_file():
        pytest.fail(
            "no oracle: build it from the Core checkout (dotnet build tools/Fuaran.Core.Oracle.Cli -c Release) "
            "or set FUARAN_CORE_ORACLE to a command line that serves the protocol"
        )
    return f'dotnet "{dll}"'


@pytest.fixture(scope="session")
def oracle_client(core: Path) -> Iterator[oracle.Client]:
    with oracle.Client.from_command_line(oracle_command_line(core)) as client:
        protocol = client.describe()
        assert protocol.startswith("1."), (
            f"the oracle serves protocol {protocol}; this harness pins major 1"
        )
        yield client
