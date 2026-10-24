# fuaran-core-py

The Fuaran Core spine in Python: canonical JSON with its proved grammar and parse limits, the
number form, SHA-256 content addresses, the decode error contract, the skeleton tree and its
ops, the op-stream chain, the content-addressed DAG and the exact decimal. It certifies against
the conformance vectors the .NET reference
([fuaran-core](https://github.com/Fuaran-Core/fuaran-core)) emits and differentially against the
reference's extracted proof models through its oracle process, and declares its compliance row
by row in `host-compliance.json`. Standard library only at runtime; Python 3.12 or later.

```python
from fuaran_core import json, address, chain

value = json.parse('{"b":1,"a":[1.5,"x"]}')  # strict: RFC 8259, one document, no duplicates
text = json.render(value)  # '{"a":[1.5,"x"],"b":1}' — the canonical bytes
digest = address.of_bytes(text)  # 'sha256:…'
record, anchor = chain.append(chain.GENESIS_ANCHOR, chain.encode_actor(chain.Human("alice")), text)
```

| Module | What it holds |
|---|---|
| `fuaran_core.json` | the value model, the strict reader with its limits record, the canonical writer |
| `fuaran_core.decode` | the decode error contract and the cursor combinators a decoder is built from |
| `fuaran_core.address` | SHA-256 as hex, and the `sha256:` content address of canonical bytes |
| `fuaran_core.tree`, `fuaran_core.ops` | the skeleton tree, its six ops and their apply |
| `fuaran_core.chain` | the op-stream chain: actors, pre-images, append and the walk |
| `fuaran_core.dag` | the content-addressed op-DAG: ids, orders, ranks, replays, the integrity walk |
| `fuaran_core.decimal` | the exact decimal as canonical text |
| `fuaran_core.oracle` | a client of the reference's oracle protocol, for test and fuzz tooling |

## Build

The gate reads the reference's vectors from a Core checkout beside this repository (or at
`FUARAN_CORE_DIR`) at the commit `core-pin.json` names, builds the reference's oracle from it,
and runs the whole suite — the vector legs and the oracle differential:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
pwsh ./run.ps1
```

`DECISIONS.md` records what the spine holds and what it does not yet, and `host-compliance.json`
is rendered by `tools/compliance.py <core checkout>` from the reference's evidence map.

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
