"""Render ``host-compliance.json`` — this spine's compliance declaration, row by row — from the
reference's evidence map and the table below of what the spine runs.

The declaration is DERIVED, never hand-maintained, so a row cannot say more than the legs
measure: for every row the reference's evidence map offers something for, one entry naming the
evidence class per family the legs run (``vector-certified``, at the count each leg asserts),
per oracle function the differential drives (``oracle-differential``, at its seed and example
count), or the premise probe the leg discharges (``host-premise``); a row none of those reach
is ``not-covered``, with the reason. ``tests/test_compliance.py`` holds the committed file to
this render, and the reference's ``compliance`` verb validates it against its tree.

Usage: ``python tools/compliance.py <core checkout> [--check]``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "host-compliance.json"

HOST = "fuaran-core-py"

#: The families the legs run whole, with the case count each leg asserts (tests/test_conformance.py,
#: tests/test_premises.py). A family absent here is not declared.
RUN: dict[str, int] = {
    "codecRefusals": 56,  # the json codec vectors; the column and profile vectors are not the spine's yet
    "decodeRejects": 47,
    "decimal": 53,  # canonical, compare, add, toFloat; the column codec and aggregates are not the spine's yet
    "skeletonApply": 25,
    "skeletonChain": 16,
    "skeletonDag": 11,
    "premiseStringModel": 29,
    "premiseFloatDigits": 163,
    "premiseInt53": 29,
    "premiseSha256": 17,
    "premiseRecursionDepth": 13,
}

#: The oracle functions the differential drives (tests/test_oracle_differential.py), the model
#: each asks, and the run it makes.
DIFFERENTIAL = {"seed": "0x5eed571", "inputs": 2000}
ORACLE: dict[str, str] = {
    "json.parse": "JsonParse",
    "tree.apply": "TreeOps",
    "chain.verify": "Chain",
}

#: Why an offered row the legs do not reach is not covered, by the row's model.
NOT_COVERED: dict[str, str] = {
    "DagFold": "the lane fold (dag.fold) is not in the spine yet",
    "WireDecode": "the wire node decoder is not in the spine: it is a wire's, not the spine's",
    "WireCanon": (
        "the escape table has no manifest to carry an adoption record; the spine runs its 38 lines "
        "(its DECISIONS.md D4); the guarded renderer differential (wire.render) is not driven yet"
    ),
    "Capability": "the capability contract is not in the spine yet; the capability and query seams are not in the spine yet",
    "Query": "the capability and query seams are not in the spine yet",
    "Propagation": "change propagation is not in the spine yet",
}


def render(core: Path) -> str:
    evidence_map = json.loads(
        (core / "docs" / "host-evidence-map.json").read_text(encoding="utf-8")
    )
    core_version = _core_version(core)
    rows = []
    for row in evidence_map["rows"]:
        families, oracle = row.get("families", []), row.get("oracle", [])
        if not families and not oracle:
            continue
        evidence: list[dict[str, object]] = []
        if row.get("level") == "assumed" and "model" not in row:
            (probe,) = families
            evidence.append(
                {"class": "host-premise", "probe": probe["family"], "cases": RUN[probe["family"]]}
            )
        else:
            for family in families:
                if family["family"] in RUN:
                    evidence.append(
                        {
                            "class": "vector-certified",
                            "family": family["family"],
                            "cases": RUN[family["family"]],
                        }
                    )
            for function in oracle:
                if function in ORACLE and ORACLE[function] == row.get("model"):
                    evidence.append(
                        {
                            "class": "oracle-differential",
                            "model": ORACLE[function],
                            "function": function,
                            "inputs": DIFFERENTIAL["inputs"],
                            "seed": DIFFERENTIAL["seed"],
                        }
                    )
        if not evidence:
            model = row.get("model")
            if model not in NOT_COVERED:
                raise SystemExit(f"row {row['id']}: no evidence and no reason for model {model!r}")
            evidence.append({"class": "not-covered", "reason": NOT_COVERED[model]})
        rows.append({"row": row["id"], "evidence": evidence})
    declaration = {
        "kind": "hostCompliance",
        "host": HOST,
        "coreVersion": core_version,
        "rows": rows,
    }
    return json.dumps(declaration, indent=2, ensure_ascii=False) + "\n"


def _core_version(core: Path) -> str:
    props = (core / "Directory.Build.props").read_text(encoding="utf-8")
    start = props.index("<Version>") + len("<Version>")
    return props[start : props.index("</Version>", start)].strip()


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3) or (len(argv) == 3 and argv[2] != "--check"):
        print("usage: compliance.py <core checkout> [--check]", file=sys.stderr)
        return 2
    rendered = render(Path(argv[1]))
    if len(argv) == 3:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current.replace("\r\n", "\n") != rendered:
            print(
                f"{OUT.name} is not what the render produces; run tools/compliance.py to regenerate it",
                file=sys.stderr,
            )
            return 1
        return 0
    OUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(rendered.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
