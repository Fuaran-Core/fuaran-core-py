# Decisions

Each entry records a decision about this package, why it was taken, and what it rules out.

## D1 — 2026-10-24 — the repository, its organisation, its licence, and how a host depends on it

- `fuaran-core-py` lives at `Fuaran-Core/fuaran-core-py`, beside the reference implementation it
  twins (`Fuaran-Core/fuaran-core`) and the Rust and Go spines (`Fuaran-Core/fuaran-core-rs`,
  `Fuaran-Core/fuaran-core-go`), and is Apache-2.0 and public from its first commit, for the
  reason the reference is: a spine every host builds on is only useful if every host can hold it.
  (Operator ruling 2026-10-24, recorded by Phase 571; the reference records it as its own
  decision.)
- The import package is `fuaran_core`; the distribution is `fuaran-core`, the name it will carry
  on PyPI. The registry name is recorded here as the choice made, and nothing is published by
  this change: `version` is `0.0.0` until a release is a deliberate act, and a release is what
  moves it. The package takes no dependency beyond the standard library at runtime (held by
  `tests/test_package.py`), and `requires-python >= 3.12`; it imports from a plain `sys.path`
  entry with no distribution metadata, which is what a browser runtime (Pyodide) and a vendored
  copy both need.
- **A host depends on it as a published distribution, by a compatible version range in its own
  `pyproject.toml`** — the only shape that resolves for a reader who has neither checkout, that a
  registry accepts in a published distribution, and that a browser runtime's installer can
  satisfy. Two other shapes were considered and declined. A committed path dependency on a
  sibling folder resolves in one layout and is a broken build in another (a worktree, a CI
  runner), as the Go spine's D1 found. A vendored copy inside a host's package resolves
  everywhere but is a second copy of the spine's bytes, with a sync tool and a pin manifest to
  keep it honest, and this declaration certifies the copy in this repository and not the one
  in a host; where the Rust and Go spines are reached by a reference to the public repository,
  Python has no equivalent short of the registry. **Until the first release is published, no
  host can depend on this package**, and the Python UI host's adoption of the spine waits on
  that release: the operator act is a version, the `fuaran-core` name on PyPI and a tag.
  Local development against an unreleased spine is `pip install -e <checkout>` into the host's
  environment, which nothing commits.

## D2 — 2026-10-24 — what the spine holds, and what it does not (a premise checked)

Phase 571 was written as an EXTRACTION of the spine out of the Python UI host. Checked against
that host, the premise holds for part of it and not for the rest:

- **Moved, verbatim in behaviour:** the canonical writer's primitives — the string escape, the
  number form (`format_finite_double`, re-laying CPython's shortest `repr` digits into the
  `.NET "R"` layout), the integer floor at ±(2^53 − 1), the UTF-16 ordinal key order (`json`).
- **Taken over, generalised:** the hash chain's pre-image and link. The UI host's typed op-record
  chain spliced its own provenance envelope into `{"seq":…,"actor":…,"op":…}` and hashed
  `prev + "|" + payload`; that is exactly the reference's chain over OPAQUE op text (`chain`), so
  the host's `compute_hash` computes through the spine's `link` and `payload`, and its one
  canonical actor encoding is the spine's `encode_actor`.
- **Not moved, because there was nothing of the kind to move:** the UI host parses JSON with the
  standard library's `json.loads` and enforces its limits over the parsed value and through the
  loader's hooks, so it has no strict reader to extract; its apply engine works over its own
  typed node and op vocabulary; and its DAG module is the codec of a UI record (it mints and
  verifies no content id). They stay in that host. What the spine holds instead is the
  reference's own contract, written for this package to the reference's vectors: the strict
  reader with its limits record and the reference's `JsonErrorKind` (`json`), the decode error
  contract and its cursor combinators over the null-free model (`decode`), the content address
  (`address`), the skeleton tree and its six ops (`tree`, `ops`), and the content-addressed DAG
  with its orders, ranks, replays and integrity walk (`dag`), generic over the op.
- **Positions are UTF-16 offsets.** A Python `str` is a sequence of code points; the reference's
  string model is UTF-16 units. The reader counts an astral code point as two units and reads a
  lone surrogate code point as the unit of its class, so a refusal's position is the reference's
  on every input, and the differential compares positions on every input rather than on ASCII
  alone.
- **The exact decimal** (`decimal`) holds the cases the reference's decimal laws certify —
  canonical, compare, add, toFloat — and no more. The UI host's own exact decimal, with its
  seven-mode rounding kernel, stays where it is for now: re-pointing it onto the spine is a later
  change, and the spine grows the kernel when a certified case needs it.
- *Declined:* moving the UI host's wire decode onto the spine's reader in the same change. That
  host's decode-tolerance contract is the shared wire corpus's, not the reference's, and the
  change would be a behavioural one across a host certified against another corpus.

## D3 — 2026-10-24 — where the vectors come from, and that the oracle is part of the gate

- The conformance legs read the reference's `conformance/` directory from a Core checkout at the
  commit `core-pin.json` names (found at `FUARAN_CORE_DIR`, or as `fuaran-core/` beside this
  repository or an ancestor of it). A missing checkout FAILS the legs: a suite that skipped its
  vectors would read green having certified nothing. The pin moves only as a deliberate act, in
  the change that needs it, with the legs re-run against the new commit.
- The oracle differential is part of the same gate, not an opt-in: `run.ps1` builds the
  reference's oracle process from that checkout (or takes `FUARAN_CORE_ORACLE`), and the suite
  drives `json.parse`, `tree.apply` and `chain.verify` first from every vector of each function's
  family and then from a Hypothesis strategy under a stated seed (`0x5eed571`) over a stated
  example count (2000 per function), with no example database, so the run is reproducible and
  the two numbers are what `host-compliance.json` declares. Hypothesis is a dev dependency only;
  the runtime stays standard library. A missing oracle fails rather than skips, for the reason
  above.
- The five divergences the Go spine's differential found before any vector did were each checked
  in this reader's design rather than rediscovered: a number is refused at the END of its token
  and a lone surrogate AFTER the unit that follows it; the token scan takes each part of a number
  as far as it runs and then judges the grammar (`1e5-0` is `1e5` and trailing text); `expect`
  refuses `ExpectedToken` at the end of the input; `updateNode`, `ins`, `rem_at` and
  `reorder_at` act on EVERY node carrying the id while `find` and `parentOf` take the first in
  pre-order, so a tree that repeats an id (which the generator builds on purpose) answers as the
  model answers; and a truncated `\u` escape is judged in UTF-16 units. The differential found no
  further divergence in 6,000 examples; a planted first-match `updateNode` and a planted
  end-of-input class each turned it red, which is the falsifier the measurement stands on.

## D4 — 2026-10-24 — what the first certification covers, and what it does not yet

Certified against the reference's vectors at the Core commit `core-pin.json` names, every count
asserted by the leg that runs it (`tests/`); the reference's adoption records carry these counts
under the host key `fuaran-core-py`:

| Family | Run | Not run, and why |
|---|---|---|
| `refusals/codec-refusals.json` | the 56 `json` vectors | the `column` and `profile` vectors: the columnar codec and the wire-profile reader are not the spine's yet |
| `decode/decode-rejects.json` | all 47 | — |
| `laws/decimal-laws.json` | the 53 `canonical`, `compare`, `add`, `toFloat` vectors | `codecDecode`, `codecEncode`, `aggregate`: the column codec and the aggregates |
| `escape/string-escape.json` | all 38 lines | — (no manifest, so no adoption record; recorded here) |
| `apply/skeleton-apply.json` | all 25 | — |
| `chain/skeleton-chain.json` | all 16 | — |
| `dag/skeleton-dag.json` | all 11 | — |
| `premises/` | every vector of all five probes | — |
| `refusals/seam-refusals.json`, `merge/`, `diff/`, the capability, field, propagation and canonical-form laws | — | the seams, the reconcile and diff, the capability contract, the schema field and unit, propagation and the IDL canonical form are not in the spine yet |

A rejection is answered in the reference's own vocabulary (its canonical rejection bytes), not
mapped to another host's codes, because this package IS the reference's twin. The `encoding/`
table is declined as the Rust and Go spines declined it: it has no manifest, and what it pins
beyond the escapes is a profile of stores this spine has never read or minted.

`host-compliance.json` is RENDERED by `tools/compliance.py` from the reference's evidence map and
the table of what the legs run, and `tests/test_compliance.py` holds the committed file to the
render, so the declaration cannot say more than the suite measures. It declares every row the
reference's evidence map offers: `vector-certified` where a leg runs the family,
`oracle-differential` for `json.parse` (`JsonParse`), `tree.apply` (`TreeOps`) and
`chain.verify` (`Chain`), `host-premise` on the five premise rows, and `not-covered` with the
reason on the rest. It validates with the reference's `compliance` verb and reads `compliant`,
with 36 of the 193 offered rows at parity: the 27 `Chain` rows, the 4 `DecodeLayer` rows and the
5 host-premise rows. Every other offered row carries at least one family or function this spine
does not answer yet. The remaining families are the next change's; this entry holds no promise
of when.
