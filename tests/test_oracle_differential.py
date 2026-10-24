"""The oracle differential: the reference's extracted proof models, run as a process (its
``docs/oracle-protocol.md``), asked about inputs nobody chose and compared with the spine's own
answer.

Two legs over one comparison per function, and the pairing is the point:

* ``test_oracle_seeds_*`` drive every vector of the function's family through the comparison,
  so the differential starts from the inputs the reference already answers;
* ``test_oracle_differential_*`` are Hypothesis property tests from the stated seed
  :data:`DIFFERENTIAL_SEED` over :data:`DIFFERENTIAL_INPUTS` examples per function, with no
  example database, so the run is reproducible on every ``pytest`` and its seed and example
  count are what ``host-compliance.json`` declares as ``oracle-differential`` evidence. The
  bounded run IS the gate's run.

The oracle is found through ``FUARAN_CORE_ORACLE`` (a command line, such as ``dotnet
<path>/fuaran-core-oracle.dll``), or built under the Core checkout's
``tools/Fuaran.Core.Oracle.Cli/bin/Release``. Like the vectors, it is not optional: a differential
that skipped its oracle would read green having compared nothing.

Positions are compared on EVERY input, not only ASCII: the spine reports UTF-16 offsets, the
reference's string model, so the two must agree wherever a refusal falls.
"""

from __future__ import annotations

import struct

import pytest
from conftest import Vectors, arr, get, has, n, s
from hypothesis import HealthCheck, Phase, given, seed, settings
from hypothesis import strategies as st

from fuaran_core import chain, decode, json, ops, oracle, tree

#: The Hypothesis seed the deterministic differential draws from.
DIFFERENTIAL_SEED = 0x5EED571

#: The number of examples the differential asks the oracle about, per function.
DIFFERENTIAL_INPUTS = 2000

DIFFERENTIAL = settings(
    max_examples=DIFFERENTIAL_INPUTS,
    deadline=None,
    database=None,
    phases=(Phase.generate, Phase.shrink),
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.filter_too_much,
    ],
)


def bits(f: float) -> str:
    return struct.pack(">d", f).hex()


# ─── json.parse ───────────────────────────────────────────────────────────────────────

# The pieces a generated document is assembled and mutated from: the grammar's tokens, every
# row's trigger, and the number form's edges.
JSON_ATOMS = [
    "{", "}", "[", "]", ",", ":", " ", "\n", "\t",
    '"a"', '"b"', '""', '"é"', '"😀"', '"\\ud800"', '"\\udc00"', '"\\x"', '"\\u12"', '"\\u12g4"', '"\t"', '"abc',
    "0", "-0", "1", "-1", "01", "1.5", ".5", "5.", "1e3", "1E+21", "1e999", "1e-400", "+1",
    "9007199254740992", "9007199254740993", "18014398509481984", "2147483647", "2147483648", "-2147483648", "-2147483649",
    "true", "false", "null", "tru", "nul", "NaN", "Infinity", "-Infinity",
    "é", "€", "😀", "\\u0é0",
]  # fmt: skip

JSON_LEAVES = [
    '"a"', '"b"', '"é"', '"😀"', "0", "1", "-1", "1.5", "1e3", "1E+21", "9007199254740992", "2147483648",
    "true", "false", "null",
]  # fmt: skip

JSON_KEYS = ['"a"', '"b"', '"c"', '"é"', '"😀"', '"\\ue000"']


def _array(items: list[str]) -> str:
    return "[" + ",".join(items) + "]"


def _object(members: list[tuple[str, str]]) -> str:
    return "{" + ",".join(k + ":" + v for k, v in members) + "}"


well_formed_json = st.recursive(
    st.sampled_from(JSON_LEAVES),
    lambda children: st.one_of(
        st.lists(children, max_size=3).map(_array),
        st.lists(st.tuples(st.sampled_from(JSON_KEYS), children), max_size=3).map(_object),
    ),
    max_leaves=12,
)

atom_sequence = st.lists(st.sampled_from(JSON_ATOMS), min_size=1, max_size=8).map("".join)


def _mutate(parts: tuple[str, int, int, str]) -> str:
    text, at, how, atom = parts
    if not text:
        return text
    i = at % len(text)
    if how == 0:
        return text[:i] + text[i + 1 :]
    if how == 1:
        return text[:i] + atom + text[i:]
    return text + text[:i]


mutated_json = st.tuples(
    well_formed_json, st.integers(0, 4096), st.integers(0, 2), st.sampled_from(JSON_ATOMS)
).map(_mutate)

json_texts = st.one_of(
    well_formed_json, well_formed_json, atom_sequence, mutated_json, st.text(max_size=12)
)


def oracle_value(v: json.Value) -> decode.Value:
    """The oracle's tagged value form as the decode layer's model."""
    assert isinstance(v, dict) and len(v) == 1, (
        f"a tagged value is a one-member object: {json.render(v)}"
    )
    (tag, payload), *_ = v.items()
    if tag == "string":
        assert isinstance(payload, str)
        return payload
    if tag == "int":
        assert isinstance(payload, str)
        return int(payload)
    if tag == "float":
        assert isinstance(payload, str)
        return float(payload)
    if tag == "bool":
        assert isinstance(payload, bool)
        return payload
    if tag == "array":
        assert isinstance(payload, list)
        return [oracle_value(item) for item in payload]
    if tag == "object":
        assert isinstance(payload, list)
        return {s(m, "key"): oracle_value(get(m, "value")) for m in payload}
    raise AssertionError(f"an unknown tag {tag}")


def same_value(a: decode.Value, b: decode.Value) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, int) or isinstance(b, int):
        return isinstance(a, int) and isinstance(b, int) and a == b
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, float) and isinstance(b, float) and bits(a) == bits(b)
    if isinstance(a, list) or isinstance(b, list):
        return (
            isinstance(a, list)
            and isinstance(b, list)
            and len(a) == len(b)
            and all(same_value(x, y) for x, y in zip(a, b, strict=True))
        )
    if isinstance(a, dict) or isinstance(b, dict):
        return (
            isinstance(a, dict)
            and isinstance(b, dict)
            and list(a) == list(b)
            and all(same_value(a[k], b[k]) for k in a)
        )
    return a == b


def encodable(text: str) -> bool:
    """A text the request can carry: one with no lone surrogate, which has no UTF-8."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def compare_json_parse(client: oracle.Client, text: str) -> None:
    """Ask ``json.parse`` about ``text`` under the oracle's default limits (depth 512, the
    reader's own STRICT) and compare the answer with the spine's null-free reading: the same
    verdict, the same refusal class, bound and position; the same value when both accept."""
    if not encodable(text):
        return
    answer = client.call("json.parse", '{"text":' + json.escape_string(text) + "}")
    mine: decode.Value | None = None
    refusal: json.Refusal | None = None
    try:
        mine = decode.read_value(text, json.STRICT)
    except json.Refusal as r:
        refusal = r
    if has(answer, "value"):
        assert refusal is None, (
            f"json.parse {text!r}: the oracle accepts, the spine refuses: {refusal}"
        )
        theirs = oracle_value(get(answer, "value"))
        assert same_value(mine, theirs), (
            f"json.parse {text!r}: values differ: {mine!r} vs {theirs!r}"
        )
    elif has(answer, "parseRefused"):
        r = get(answer, "parseRefused")
        assert isinstance(refusal, json.JsonError), (
            f"json.parse {text!r}: the oracle refuses {json.render(r)}, the spine {refusal!r}"
        )
        assert refusal.kind.value == s(r, "kind"), (
            f"json.parse {text!r}: the oracle refuses {s(r, 'kind')}, the spine {refusal}"
        )
        assert refusal.at == int(n(r, "at")), (
            f"json.parse {text!r}: refused at {refusal.at}, the oracle at {int(n(r, 'at'))}"
        )
    elif has(answer, "parseLimit"):
        limit = get(answer, "parseLimit")
        assert isinstance(refusal, json.LimitBreach) and refusal.limit.value == s(limit, "limit"), (
            f"json.parse {text!r}: the oracle refuses at bound {s(limit, 'limit')}, the spine {refusal!r}"
        )
        assert refusal.at == int(n(limit, "at")), (
            f"json.parse {text!r}: breach at {refusal.at}, the oracle at {int(n(limit, 'at'))}"
        )
    else:
        pytest.fail(f"json.parse {text!r}: an unknown answer {json.render(answer)}")


def json_parse_seeds(vectors: Vectors) -> list[str]:
    seeds = [
        s(v, "input")
        for v in arr(vectors.read("refusals/codec-refusals.json"), "vectors")
        if s(v, "codec") == "json"
    ]
    seeds += [
        s(v, "input")
        for v in arr(vectors.read("decode/decode-rejects.json"), "vectors")
        if not has(v, "limits")
    ]
    seeds += [s(v, "token") for v in arr(vectors.read("premises/int53.json"), "vectors")]
    seeds += [
        s(v, "text")
        for v in arr(vectors.read("premises/string-model.json"), "vectors")
        if has(v, "text")
    ]
    return seeds


def test_oracle_seeds_json_parse(oracle_client: oracle.Client, vectors: Vectors) -> None:
    seeds = json_parse_seeds(vectors)
    assert len(seeds) > 100
    for text in seeds:
        compare_json_parse(oracle_client, text)


@seed(DIFFERENTIAL_SEED)
@DIFFERENTIAL
@given(text=json_texts)
def test_oracle_differential_json_parse(oracle_client: oracle.Client, text: str) -> None:
    compare_json_parse(oracle_client, text)


# ─── tree.apply ───────────────────────────────────────────────────────────────────────

TREE_IDS = ["root", "a", "a1", "a2", "b", "b1", "c", "n1", "n2", "zz"]
TREE_KINDS = ["doc", "section", "para"]

tree_ids = st.sampled_from(TREE_IDS)
tree_kinds = st.sampled_from(TREE_KINDS)


@st.composite
def trees(draw: st.DrawFn) -> tree.Node:
    """A tree under ``root`` over the fixed ids. Ids are unique by default; with a small
    probability an id repeats, so the differential covers the trees the reference's apply never
    states it assumes away (DECISIONS.md D3)."""
    allow_repeats = draw(st.integers(0, 9)) == 0
    used = {"root"}
    root = tree.Node("root", "doc", [])

    def grow(node: tree.Node, depth: int) -> None:
        if depth == 0:
            return
        for _ in range(draw(st.integers(0, 3))):
            node_id = draw(tree_ids)
            if node_id in used and not allow_repeats:
                continue
            used.add(node_id)
            child = tree.Node(node_id, draw(tree_kinds), [])
            node.children.append(child)
            grow(child, depth - 1)

    grow(root, 3)
    return root


leaves = st.builds(tree.Node, tree_ids, tree_kinds, st.just([]))

skeleton_ops: st.SearchStrategy[ops.Op] = st.recursive(
    st.one_of(
        st.builds(ops.InsertChild, tree_ids, leaves),
        st.builds(ops.RemoveNode, tree_ids),
        st.builds(ops.MoveNode, tree_ids, tree_ids),
        st.builds(ops.ReorderChildren, tree_ids, st.lists(tree_ids, max_size=3).map(tuple)),
        st.builds(ops.UpdateNode, leaves),
    ),
    lambda children: st.lists(children, max_size=3).map(lambda members: ops.Batch(tuple(members))),
    max_leaves=6,
)


def oracle_tree(node: tree.Node) -> str:
    """A tree in the oracle's own form, ``{"id","kind","children"}``."""
    items = [oracle_tree(c) for c in node.children]
    return (
        '{"id":'
        + json.escape_string(node.id)
        + ',"kind":'
        + json.escape_string(node.kind)
        + ',"children":'
        + json.render_array(items)
        + "}"
    )


def oracle_op(op: ops.Op) -> str:
    """An op in the oracle's own form."""
    if isinstance(op, ops.InsertChild):
        return (
            '{"op":"insertChild","parent":'
            + json.escape_string(op.parent)
            + ',"node":'
            + oracle_tree(op.node)
            + "}"
        )
    if isinstance(op, ops.RemoveNode):
        return '{"op":"removeNode","node":' + json.escape_string(op.target) + "}"
    if isinstance(op, ops.MoveNode):
        return (
            '{"op":"moveNode","node":'
            + json.escape_string(op.target)
            + ',"newParent":'
            + json.escape_string(op.new_parent)
            + "}"
        )
    if isinstance(op, ops.ReorderChildren):
        order = json.render_array([json.escape_string(i) for i in op.order])
        return (
            '{"op":"reorderChildren","parent":'
            + json.escape_string(op.parent)
            + ',"order":'
            + order
            + "}"
        )
    if isinstance(op, ops.Batch):
        return '{"op":"batch","ops":' + json.render_array([oracle_op(m) for m in op.ops]) + "}"
    return '{"op":"updateNode","node":' + oracle_tree(op.node) + "}"


def tree_of_oracle(v: json.Value) -> tree.Node:
    children = json.field_of(v, "children")
    return tree.Node(
        s(v, "id"),
        s(v, "kind"),
        [tree_of_oracle(c) for c in children] if isinstance(children, list) else [],
    )


def rejection_of_oracle(r: json.Value) -> str:
    """The oracle's rejection as the spine's rejection bytes."""
    kind = s(r, "rejection")
    if kind == "unknownNode":
        return ops.UnknownNode(s(r, "target")).encode()
    if kind == "duplicateId":
        return ops.DuplicateId(s(r, "id")).encode()
    if kind == "cannotRemoveRoot":
        return ops.CannotRemoveRoot().encode()
    if kind == "wouldNestUnderSelf":
        return ops.WouldNestUnderSelf(s(r, "node")).encode()
    if kind == "reorderMismatch":
        return ops.ReorderMismatch(s(r, "parent")).encode()
    return kind


def compare_tree_apply(client: oracle.Client, base: tree.Node, op: ops.Op) -> None:
    answer = client.call(
        "tree.apply", '{"tree":' + oracle_tree(base) + ',"op":' + oracle_op(op) + "}"
    )
    mine, rejection = ops.apply(base, op)
    where = f"tree.apply {op.encode()} on {base.encode()}"
    if has(answer, "applied"):
        assert rejection is None, (
            f"{where}: the oracle applies, the spine rejects {rejection.encode()}"
        )
        theirs = tree_of_oracle(get(answer, "applied"))
        assert mine == theirs, (
            f"{where}: {mine.encode() if mine else None}, the oracle {theirs.encode()}"
        )
    elif has(answer, "rejected"):
        want = rejection_of_oracle(get(answer, "rejected"))
        assert rejection is not None, f"{where}: the oracle rejects {want}, the spine applies"
        assert rejection.encode() == want, f"{where}: {rejection.encode()}, the oracle {want}"
    else:
        pytest.fail(f"{where}: an unknown answer {json.render(answer)}")


def test_oracle_seeds_tree_apply(oracle_client: oracle.Client, vectors: Vectors) -> None:
    ran = 0
    for v in arr(vectors.read("apply/skeleton-apply.json"), "vectors"):
        inp = get(v, "input")
        compare_tree_apply(oracle_client, tree.parse(s(inp, "tree")), ops.parse(s(inp, "op")))
        ran += 1
    assert ran == 25


@seed(DIFFERENTIAL_SEED)
@DIFFERENTIAL
@given(base=trees(), op=skeleton_ops)
def test_oracle_differential_tree_apply(
    oracle_client: oracle.Client, base: tree.Node, op: ops.Op
) -> None:
    compare_tree_apply(oracle_client, base, op)


# ─── chain.verify ─────────────────────────────────────────────────────────────────────

CHAIN_ACTORS = [
    '{"kind":"human","id":"alice"}',
    '{"kind":"human","id":"bob"}',
    '{"kind":"agent","model":"m","version":"1","id":"x"}',
]
CHAIN_OPS = ["{}", '{"$type":"removeNode","target":"a1"}', '{"a":1}', "[]", '"é😀"']


@st.composite
def chains(draw: st.DrawFn) -> list[chain.Record]:
    """An intact run of records from the genesis anchor, with probability about a half tampered
    in one member of one record."""
    at = chain.GENESIS_ANCHOR
    records: list[chain.Record] = []
    for _ in range(draw(st.integers(0, 5))):
        record, at = chain.append(
            at, draw(st.sampled_from(CHAIN_ACTORS)), draw(st.sampled_from(CHAIN_OPS))
        )
        records.append(record)
    if records and draw(st.booleans()):
        i = draw(st.integers(0, len(records) - 1))
        r = records[i]
        how = draw(st.integers(0, 4))
        if how == 0:
            r = chain.Record(r.seq + draw(st.integers(1, 3)), r.actor, r.op, r.prev_hash, r.hash)
        elif how == 1:
            r = chain.Record(r.seq, r.actor, r.op, "deadbeef", r.hash)
        elif how == 2:
            r = chain.Record(r.seq, r.actor, r.op, r.prev_hash, r.hash[1:] + "0")
        elif how == 3:
            r = chain.Record(r.seq, r.actor, '{"tampered":true}', r.prev_hash, r.hash)
        else:
            r = chain.Record(r.seq, '{"kind":"human","id":"mallory"}', r.op, r.prev_hash, r.hash)
        records[i] = r
    return records


def oracle_records(records: list[chain.Record]) -> str:
    items = [
        '{"seq":' + str(r.seq) + ',"actor":' + json.escape_string(r.actor) + ',"op":' + json.escape_string(r.op)
        + ',"prev":' + json.escape_string(r.prev_hash) + ',"hash":' + json.escape_string(r.hash) + "}"
        for r in records
    ]  # fmt: skip
    return json.render_array(items)


def compare_chain_verify(client: oracle.Client, records: list[chain.Record]) -> None:
    answer = client.call(
        "chain.verify", '{"hash":"sha256","records":' + oracle_records(records) + "}"
    )
    _, brk = chain.walk(chain.GENESIS_ANCHOR, records)
    where = f"chain.verify {oracle_records(records)}"
    if has(answer, "intact"):
        assert brk is None, f"{where}: the oracle finds it intact, the spine {brk}"
    elif has(answer, "broken"):
        b = get(answer, "broken")
        assert brk is not None, (
            f"{where}: the oracle finds {json.render(b)}, the spine finds it intact"
        )
        theirs = chain.Break(
            int(n(b, "index")), chain.BreakReason(s(b, "reason")), s(b, "expected"), s(b, "got")
        )
        assert brk == theirs, f"{where}: the spine finds {brk}, the oracle {theirs}"
    else:
        pytest.fail(f"{where}: an unknown answer {json.render(answer)}")


def test_oracle_seeds_chain_verify(oracle_client: oracle.Client, vectors: Vectors) -> None:
    ran = 0
    for v in arr(vectors.read("chain/skeleton-chain.json"), "vectors"):
        if s(v, "case") != "walk":
            continue
        records = [
            chain.Record(
                int(n(r, "seq")), s(r, "actor"), s(r, "op"), s(r, "prevHash"), s(r, "hash")
            )
            for r in arr(get(v, "input"), "records")
        ]
        compare_chain_verify(oracle_client, records)
        ran += 1
    assert ran > 0


@seed(DIFFERENTIAL_SEED)
@DIFFERENTIAL
@given(records=chains())
def test_oracle_differential_chain_verify(
    oracle_client: oracle.Client, records: list[chain.Record]
) -> None:
    compare_chain_verify(oracle_client, records)
