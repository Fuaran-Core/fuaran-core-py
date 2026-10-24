"""The vector legs: one per family the spine runs, each held to its manifest's count."""

from __future__ import annotations

from conftest import Vectors, arr, get, has, n, s, str_items

from fuaran_core import address, chain, dag, decimal, decode, json, ops, tree


def actor_of(text: str) -> chain.Actor:
    actor = chain.parse_actor(text)
    assert chain.encode_actor(actor) == text
    return actor


def tree_of(text: str) -> tree.Node:
    node = tree.parse(text)
    assert node.encode() == text, f"a tree's canonical bytes: {node.encode()}, want {text}"
    return node


def op_of(text: str) -> ops.Op:
    op = ops.parse(text)
    assert op.encode() == text, f"an op's canonical bytes: {op.encode()}, want {text}"
    return op


# ─── refusals/codec-refusals.json — the JSON reader ───────────────────────────────────


def test_codec_refusals_json_vectors(vectors: Vectors) -> None:
    ran = 0
    for v in vectors.family("refusals", "codec-refusals.json", "codecRefusals"):
        if s(v, "codec") != "json":
            continue
        name = s(v, "name")
        value, refusal = json.try_parse(s(v, "input"))
        if has(v, "refusal"):
            assert isinstance(refusal, json.JsonError), (
                f"{name}: expected {s(v, 'refusal')}, got {refusal!r}"
            )
            assert refusal.kind.value == s(v, "refusal"), (
                f"{name}: expected {s(v, 'refusal')}, got {refusal}"
            )
        else:
            assert refusal is None, f"{name}: refused {refusal}"
            assert json.render(value) == s(v, "canonical"), f"{name}: rendered {json.render(value)}"
        ran += 1
    # The column and profile vectors (45) need the columnar codec and the wire profile, which
    # the spine does not hold yet (DECISIONS.md D3).
    assert ran == 56


# ─── decode/decode-rejects.json — the decode error contract ───────────────────────────

ANY: json.Value = {"$type": "any"}


def _field_or_any(v: json.Value, k: str) -> json.Value:
    return v[k] if isinstance(v, dict) and k in v else ANY


def read_shape(defs: json.Value, shape: json.Value, at: decode.Cursor) -> None:
    """Read the vector's shape grammar with the spine's combinators exactly as the reference's
    shape decoder reads it."""
    kind = s(shape, "$type")
    if kind == "string":
        at.string()
    elif kind == "int":
        at.int()
    elif kind == "float":
        at.float()
    elif kind == "bool":
        at.bool()
    elif kind == "any":
        return
    elif kind == "list":
        of = _field_or_any(shape, "of")
        maximum = json.field_of(shape, "maxItems")
        items = at.items_at_most(int(maximum)) if isinstance(maximum, float) else at.items()
        for item in items:
            read_shape(defs, of, item)
    elif kind == "object":
        fields = json.field_of(shape, "fields")
        fields = fields if isinstance(fields, list) else []
        if json.field_of(shape, "closed") is True:
            at.closed([s(f, "name") for f in fields])
        for f in fields:
            sub = _field_or_any(f, "shape")
            if json.field_of(f, "optional") is True:
                c = at.optional(s(f, "name"))
                if c is not None:
                    read_shape(defs, sub, c)
            else:
                read_shape(defs, sub, at.field(s(f, "name")))
        if not fields:
            at.optional("")  # still an object
    elif kind == "tagged":
        key = json.field_of(shape, "key")
        key = key if isinstance(key, str) else "kind"
        cases = arr(shape, "cases")
        tag = at.tag(key, [s(c, "tag") for c in cases])
        admit = json.field_of(shape, "admit")
        if isinstance(admit, list) and tag not in admit:
            raise at.field(key).fail(decode.Code.NOT_ADMITTED, f"'{tag}' is not admitted here")
        for c in cases:
            if s(c, "tag") == tag:
                read_shape(defs, get(c, "shape"), at)
                return
        raise AssertionError(f"no case for {tag}")
    elif kind == "intRange":
        at.int_range(int(n(shape, "min")), int(n(shape, "max")))
    elif kind == "ref":
        definition = json.field_of(defs, s(shape, "name"))
        if definition is None:
            raise at.fail(decode.Code.SCHEMA_FAULT, "an unresolved shape")
        read_shape(defs, definition, at)
    else:
        raise AssertionError(f"unknown shape {kind}")


def limits_of(v: json.Value) -> json.Limits:
    limits = json.field_of(v, "limits")
    if limits is None:
        return json.STRICT
    return json.Limits(
        depth=int(n(limits, "depth")),
        string_length=int(n(limits, "stringLength")),
        array_length=int(n(limits, "arrayLength")),
        object_members=int(n(limits, "objectMembers")),
        document_bytes=int(n(limits, "documentBytes")),
    )


def test_decode_rejects_vectors(vectors: Vectors) -> None:
    ran = 0
    for v in vectors.family("decode", "decode-rejects.json", "decodeRejects"):
        name = s(v, "name")
        defs = json.field_of(v, "definitions") or {}
        outcome: decode.DecodeError | None = None
        try:
            value = decode.parse(s(v, "input"), limits_of(v))
            read_shape(defs, get(v, "shape"), decode.Cursor.root(value))
        except decode.DecodeError as e:
            outcome = e
        refusal = json.field_of(v, "refusal")
        if refusal is None:
            assert outcome is None, f"{name}: refused {outcome}"
            assert json.field_of(v, "accepted") is True, f"{name}: accepted without saying so"
        else:
            assert outcome is not None, f"{name}: expected {json.render(refusal)}, accepted"
            assert outcome.code.value == s(refusal, "code"), f"{name}: {outcome}"
            assert decode.path_json(outcome.path) == json.render(get(refusal, "path")), (
                f"{name}: {outcome}"
            )
        ran += 1
    assert ran == 47


# ─── laws/decimal-laws.json — the exact decimal ───────────────────────────────────────


def test_decimal_law_vectors(vectors: Vectors) -> None:
    ran = 0
    for v in vectors.family("laws", "decimal-laws.json", "decimal"):
        case, vector_id, inp, expected = (
            s(v, "case"),
            s(v, "id"),
            get(v, "input"),
            get(v, "expected"),
        )
        accept = s(expected, "verdict") == "accept"
        answer: str | None
        want: str | None = None
        if case == "canonical":
            answer = decimal.canonical(s(inp, "text"))
            want = s(expected, "canonical") if accept else None
        elif case == "compare":
            order = decimal.compare(s(inp, "a"), s(inp, "b"))
            answer = None if order is None else str(order)
            want = str(int(n(expected, "order"))) if accept else None
        elif case == "add":
            answer = decimal.add(s(inp, "a"), s(inp, "b"))
            want = s(expected, "sum") if accept else None
        elif case == "toFloat":
            f = decimal.to_float(s(inp, "text"))
            answer = None if f is None else json.format_finite_double(f)
            want = s(expected, "float") if accept else None
        else:
            # The column codec and the aggregates (22) need the columnar codec, which the spine
            # does not hold yet (DECISIONS.md D3).
            continue
        assert (answer is not None) == accept, (
            f"{vector_id}: accepted={answer is not None}, want {accept}"
        )
        if accept:
            assert answer == want, f"{vector_id}: {answer}, want {want}"
        ran += 1
    assert ran == 53


# ─── escape/string-escape.json — the one string spelling ──────────────────────────────


def test_string_escape_lines(vectors: Vectors) -> None:
    doc = vectors.read("escape/string-escape.json")
    ran = 0
    for line in arr(doc, "lines"):
        assert isinstance(line, str)
        fields = line.split("\t")
        assert len(fields) == 3, f"{line}: three fields"
        name, spelling, pre_image = fields
        if pre_image.startswith('{"seq"'):
            actor = actor_of(spelling)
            assert chain.payload(0, chain.encode_actor(actor), "{}") == pre_image, name
        else:
            if name.startswith("U+"):
                ch = chr(int(name.removeprefix("U+"), 16))
            else:
                ch = s(json.parse(pre_image), "id")
            assert json.escape_string(ch) == '"' + spelling + '"', (
                f"{name}: escaped {json.escape_string(ch)}"
            )
            assert chain.encode_actor(chain.Human(ch)) == pre_image, f"{name}: actor"
        ran += 1
    assert ran == 38


# ─── apply/skeleton-apply.json — the skeleton ops ─────────────────────────────────────


def test_skeleton_apply_vectors(vectors: Vectors) -> None:
    ran = 0
    for v in vectors.family("apply", "skeleton-apply.json", "skeletonApply"):
        vector_id, inp, expected = s(v, "id"), get(v, "input"), get(v, "expected")
        base, op = tree_of(s(inp, "tree")), op_of(s(inp, "op"))
        result, rejection = ops.apply(base, op)
        if s(expected, "verdict") == "accept":
            assert rejection is None and result is not None, f"{vector_id}: rejected {rejection}"
            text = result.encode()
            assert text == s(expected, "tree"), f"{vector_id}: tree {text}"
            assert address.of_bytes(text) == s(expected, "hash"), f"{vector_id}: hash"
        else:
            assert rejection is not None, f"{vector_id}: applied"
            assert rejection.encode() == s(expected, "rejection"), (
                f"{vector_id}: {rejection.encode()}"
            )
        ran += 1
    assert ran == 25


# ─── chain/skeleton-chain.json — the op-stream chain ──────────────────────────────────


def anchor_of(v: json.Value) -> chain.Anchor:
    return chain.Anchor(s(v, "prevHash"), int(n(v, "seq")))


def record_of(r: json.Value) -> chain.Record:
    return chain.Record(int(n(r, "seq")), s(r, "actor"), s(r, "op"), s(r, "prevHash"), s(r, "hash"))


def test_skeleton_chain_vectors(vectors: Vectors) -> None:
    ran = 0
    for v in vectors.family("chain", "skeleton-chain.json", "skeletonChain"):
        vector_id, inp, expected = s(v, "id"), get(v, "input"), get(v, "expected")
        anchor = anchor_of(get(inp, "anchor"))
        case = s(v, "case")
        if case == "append":
            at = anchor
            want = arr(expected, "records")
            entries = arr(inp, "entries")
            assert len(entries) == len(want), vector_id
            for i, (e, w) in enumerate(zip(entries, want, strict=True)):
                r, at = chain.append(at, s(e, "actor"), s(e, "op"))
                got = (r.seq, r.prev_hash, r.payload(), r.hash)
                want_record = (int(n(w, "seq")), s(w, "prevHash"), s(w, "payload"), s(w, "hash"))
                assert got == want_record, f"{vector_id}: record {i}: {r}"
            assert at == anchor_of(get(expected, "tip")), f"{vector_id}: the tip {at}"
        elif case == "walk":
            records = [record_of(r) for r in arr(inp, "records")]
            tip, brk = chain.walk(anchor, records)
            if s(expected, "verdict") == "intact":
                assert brk is None, f"{vector_id}: {brk}"
                assert tip == anchor_of(get(expected, "tip")), f"{vector_id}: the tip {tip}"
            else:
                assert brk is not None, f"{vector_id}: intact"
                want_break = chain.Break(
                    int(n(expected, "index")),
                    chain.BreakReason(s(expected, "reason")),
                    s(expected, "expected"),
                    s(expected, "got"),
                )
                assert brk == want_break, f"{vector_id}: break {brk}"
        else:
            raise AssertionError(f"{vector_id}: unknown case {case}")
        ran += 1
    assert ran == 16


# ─── dag/skeleton-dag.json — the op-DAG ───────────────────────────────────────────────


def apply_tree(op: ops.Op, t: tree.Node) -> tuple[tree.Node | None, ops.Rejection | None]:
    return ops.apply(t, op)


def test_skeleton_dag_vectors(vectors: Vectors) -> None:
    ran = 0
    for v in vectors.family("dag", "skeleton-dag.json", "skeletonDag"):
        vector_id, inp, expected = s(v, "id"), get(v, "input"), get(v, "expected")
        case = s(v, "case")
        if case == "build":
            check_build(vector_id, inp, expected)
        elif case == "verify":
            nodes = [
                dag.Node(
                    s(x, "id"),
                    tuple(str_items(x, "parents")),
                    actor_of(s(x, "actor")),
                    op_of(s(x, "op")),
                )
                for x in arr(inp, "nodes")
            ]
            brk = dag.Dag(nodes).first_break()
            if s(expected, "verdict") == "intact":
                assert brk is None, f"{vector_id}: {brk}"
            else:
                want_break = dag.Break(
                    s(expected, "node"),
                    dag.BreakReason(s(expected, "reason")),
                    s(expected, "expected"),
                    s(expected, "got"),
                )
                assert brk == want_break, f"{vector_id}: break {brk}"
        else:
            raise AssertionError(f"{vector_id}: unknown case {case}")
        ran += 1
    assert ran == 11


def check_build(vector_id: str, inp: json.Value, expected: json.Value) -> None:
    state0 = tree_of(s(inp, "state0"))
    d: dag.Dag[ops.Op] = dag.Dag()
    ids: dict[str, str] = {}  # label -> id
    names: dict[str, str] = {}  # id -> the first label that wrote it
    writes, want_writes = arr(inp, "writes"), arr(expected, "writes")
    assert len(writes) == len(want_writes), vector_id
    for w, want in zip(writes, want_writes, strict=True):
        label = s(w, "label")
        parents = [ids[p[1:]] if p.startswith("@") else p for p in str_items(w, "parents")]
        actor, op = actor_of(s(w, "actor")), op_of(s(w, "op"))
        verb = s(w, "verb")
        if verb == "appendOn":
            node, fault = d.append_on(actor, op, parents)
        elif verb == "mergeAll":
            node, fault = d.merge_all(actor, op, parents)
        else:
            raise AssertionError(f"{vector_id}: unknown verb {verb}")
        assert s(want, "label") == label, vector_id
        if fault is None:
            assert node == s(want, "id"), f"{vector_id}: write {label}: id {node}"
            ids[label] = node
            names.setdefault(node, label)
        else:
            assert fault.encode() == s(want, "refused"), (
                f"{vector_id}: write {label}: {fault.encode()}"
            )

    def labels(nodes: list[str]) -> list[str]:
        return [names[x] for x in nodes]

    assert labels(d.heads()) == str_items(expected, "heads"), f"{vector_id}: heads"
    order, cyc = d.total_order()
    assert cyc is None, f"{vector_id}: {cyc}"
    assert labels(order) == str_items(expected, "order"), f"{vector_id}: order {labels(order)}"
    ranks, _ = d.ranks()
    want_ranks = get(expected, "ranks")
    assert isinstance(want_ranks, dict)
    assert {names[k]: r for k, r in ranks.items()} == {k: int(r) for k, r in want_ranks.items()}, (
        f"{vector_id}: ranks"
    )

    replays, heads = arr(expected, "replays"), d.heads()
    assert len(replays) == len(heads), f"{vector_id}: {len(replays)} replays for {len(heads)} heads"
    for head, want in zip(heads, replays, strict=True):
        assert names[head] == s(want, "head"), vector_id
        check_replay(vector_id, names, want, *d.replay_to(state0, head, apply_tree))
    check_replay(vector_id, names, get(expected, "replayAll"), *d.replay_all(state0, apply_tree))


def check_replay(
    vector_id: str,
    names: dict[str, str],
    want: json.Value,
    got: tree.Node | None,
    fault: dag.ReplayFault[ops.Rejection] | None,
) -> None:
    if s(want, "verdict") == "accept":
        assert fault is None and got is not None, f"{vector_id}: replay: {fault}"
        assert got.encode() == s(want, "tree") and address.of_bytes(got.encode()) == s(
            want, "hash"
        ), vector_id
    else:
        assert isinstance(fault, dag.Rejected), f"{vector_id}: replay: {fault}"
        assert names[fault.node] == s(want, "node"), f"{vector_id}: rejected at {names[fault.node]}"
        assert fault.rejection.encode() == s(want, "rejection"), (
            f"{vector_id}: {fault.rejection.encode()}"
        )
