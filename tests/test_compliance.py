"""The compliance declaration is what the render produces, and it names what the legs run."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))

import compliance
from test_oracle_differential import DIFFERENTIAL_INPUTS, DIFFERENTIAL_SEED


def test_the_committed_declaration_is_the_render(core: Path) -> None:
    committed = (ROOT / "host-compliance.json").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == compliance.render(core), (
        "host-compliance.json is stale: run tools/compliance.py <core>"
    )


def test_the_declared_differential_is_the_one_the_suite_runs() -> None:
    assert compliance.DIFFERENTIAL == {
        "seed": f"0x{DIFFERENTIAL_SEED:x}",
        "inputs": DIFFERENTIAL_INPUTS,
    }


def test_the_declaration_declares_every_offered_row(core: Path) -> None:
    evidence_map = json.loads(
        (core / "docs" / "host-evidence-map.json").read_text(encoding="utf-8")
    )
    offered = {r["id"] for r in evidence_map["rows"] if r.get("families") or r.get("oracle")}
    declared = {
        r["row"]
        for r in json.loads((ROOT / "host-compliance.json").read_text(encoding="utf-8"))["rows"]
    }
    assert declared == offered


def test_the_pin_names_a_commit() -> None:
    pin = json.loads((ROOT / "core-pin.json").read_text(encoding="utf-8"))
    assert pin["kind"] == "core-pin" and pin["repository"] == "Fuaran-Core/fuaran-core"
    assert len(pin["sha"]) == 40 and all(c in "0123456789abcdef" for c in pin["sha"])
