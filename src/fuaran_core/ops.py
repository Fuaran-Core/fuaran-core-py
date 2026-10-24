"""The skeleton ops and their apply — the reference's tree-op contract over the
:class:`fuaran_core.tree.Node` witness, with no domain policy: every node may hold children,
and a rejection names its class and the id it is about.

| Op                | Refused when, in this order |
|-------------------|-----------------------------|
| ``insertChild``   | an id of the graft is already in the tree or repeats inside the graft (``duplicateId``, the first in pre-order); the parent is absent (``unknownNode``) |
| ``removeNode``    | the target is the root (``cannotRemoveRoot``); it is absent (``unknownNode``) |
| ``moveNode``      | the target is the root (``cannotRemoveRoot``); the target, then the new parent, is absent (``unknownNode``); the new parent is the target or below it (``wouldNestUnderSelf``) |
| ``reorderChildren`` | the parent is absent (``unknownNode``); the order is not a permutation of its children's ids (``reorderMismatch``) |
| ``updateNode``    | no node has the payload's id (``unknownNode``); the kind is rewritten in place and the children kept |
| ``batch``         | any member is refused: all or nothing, and the member's own rejection is the answer |

An inserted node is appended to its parent's children, and a moved one to its new parent's.
Ops and rejections are ``$type``-discriminated canonical JSON. Certified against the
reference's ``apply/skeleton-apply.json``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from . import decode, json, tree

# ── The ops ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InsertChild:
    """Appends ``node`` under ``parent``."""

    parent: str
    node: tree.Node

    def encode(self) -> str:
        return (
            '{"$type":"insertChild","node":'
            + self.node.encode()
            + ',"parent":'
            + json.escape_string(self.parent)
            + "}"
        )

    canonical = encode


@dataclass(frozen=True)
class RemoveNode:
    """Detaches the target and its subtree."""

    target: str

    def encode(self) -> str:
        return '{"$type":"removeNode","target":' + json.escape_string(self.target) + "}"

    canonical = encode


@dataclass(frozen=True)
class MoveNode:
    """Detaches the target and appends it under ``new_parent``."""

    target: str
    new_parent: str

    def encode(self) -> str:
        return (
            '{"$type":"moveNode","newParent":'
            + json.escape_string(self.new_parent)
            + ',"target":'
            + json.escape_string(self.target)
            + "}"
        )

    canonical = encode


@dataclass(frozen=True)
class ReorderChildren:
    """Permutes the parent's children into ``order``."""

    parent: str
    order: tuple[str, ...]

    def encode(self) -> str:
        items = json.render_array([json.escape_string(i) for i in self.order])
        return (
            '{"$type":"reorderChildren","order":'
            + items
            + ',"parent":'
            + json.escape_string(self.parent)
            + "}"
        )

    canonical = encode


@dataclass(frozen=True)
class Batch:
    """Applies its members in order, all or nothing."""

    ops: tuple[Op, ...]

    def encode(self) -> str:
        return '{"$type":"batch","ops":' + json.render_array([op.encode() for op in self.ops]) + "}"

    canonical = encode


@dataclass(frozen=True)
class UpdateNode:
    """Rewrites the kind of the node with the payload's id, keeping its children."""

    node: tree.Node

    def encode(self) -> str:
        return '{"$type":"updateNode","node":' + self.node.encode() + "}"

    canonical = encode


#: A skeleton op. Each has ``encode()`` (its canonical bytes) and ``canonical()`` (the same,
#: under the name a content-addressed DAG hashes an op by), so a skeleton op is a DAG's op
#: with no adapter.
type Op = InsertChild | RemoveNode | MoveNode | ReorderChildren | Batch | UpdateNode

OP_TAGS = ("insertChild", "removeNode", "moveNode", "reorderChildren", "batch", "updateNode")


def decode_op(at: decode.Cursor) -> Op:
    """Read an op, each refusal at its path."""
    tag = at.tag("$type", OP_TAGS)
    if tag == "insertChild":
        parent = at.field("parent").string()
        return InsertChild(parent, tree.decode_node(at.field("node")))
    if tag == "removeNode":
        return RemoveNode(at.field("target").string())
    if tag == "moveNode":
        target = at.field("target").string()
        return MoveNode(target, at.field("newParent").string())
    if tag == "reorderChildren":
        parent = at.field("parent").string()
        order = tuple(item.string() for item in at.field("order").items())
        return ReorderChildren(parent, order)
    if tag == "batch":
        return Batch(tuple(decode_op(item) for item in at.field("ops").items()))
    return UpdateNode(tree.decode_node(at.field("node")))


def parse(text: str) -> Op:
    """Read an op from its JSON text; a refusal is a :class:`fuaran_core.decode.DecodeError`."""
    return decode_op(decode.Cursor.root(decode.parse(text, json.STRICT)))


# ── The rejections ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DuplicateId:
    """An id of the graft is already in the tree or repeats inside the graft."""

    id: str

    def encode(self) -> str:
        return '{"$type":"duplicateId","id":' + json.escape_string(self.id) + "}"


@dataclass(frozen=True)
class UnknownNode:
    """No node has the target's id."""

    target: str

    def encode(self) -> str:
        return '{"$type":"unknownNode","target":' + json.escape_string(self.target) + "}"


@dataclass(frozen=True)
class CannotRemoveRoot:
    """The root is the target of a remove or a move."""

    def encode(self) -> str:
        return '{"$type":"cannotRemoveRoot"}'


@dataclass(frozen=True)
class WouldNestUnderSelf:
    """The new parent is the target or below it."""

    target: str

    def encode(self) -> str:
        return '{"$type":"wouldNestUnderSelf","target":' + json.escape_string(self.target) + "}"


@dataclass(frozen=True)
class ReorderMismatch:
    """The order is not a permutation of the parent's children."""

    parent: str

    def encode(self) -> str:
        return '{"$type":"reorderMismatch","parent":' + json.escape_string(self.parent) + "}"


#: Why an op was refused: its class and the id it is about, each with ``encode()``.
type Rejection = DuplicateId | UnknownNode | CannotRemoveRoot | WouldNestUnderSelf | ReorderMismatch


# ── The apply ────────────────────────────────────────────────────────────────────────
#
# The tree primitives below are the reference's, clause for clause, over the tree AS IT STANDS
# — a well-formed tree holds each id once, and on such a tree "every node carrying the id" and
# "the node with the id" coincide. The reference's apply ASSUMES well-formedness and never
# states it, so on a tree that repeats an id its answer is still defined, and these are that
# answer: the reference's updateNode rebuilds EVERY node whose id matches, and tryFind /
# parentOf resolve to the FIRST in pre-order. The oracle differential compares the two on
# every tree the fuzzer builds, well-formed or not, so the spine answers as the model does
# rather than as a first-match walk happens to.


def _first_duplicate(t: tree.Node, graft: tree.Node) -> str | None:
    """The first id of ``graft``, in pre-order, already in ``t`` or repeated inside the graft
    itself; ``None`` when there is none."""
    seen = set(t.ids())
    for node_id in graft.ids():
        if node_id in seen:
            return node_id
        seen.add(node_id)
    return None


def _has_id(t: tree.Node, node_id: str) -> bool:
    return t.find(node_id) is not None


def _parent_of(t: tree.Node, node_id: str) -> str | None:
    """The reference's ``Tree.parentOf``: the first pre-order node one of whose children
    carries ``node_id``."""
    for child in t.children:
        if child.id == node_id:
            return t.id
    for child in t.children:
        p = _parent_of(child, node_id)
        if p is not None:
            return p
    return None


def _every_node(t: tree.Node, node_id: str, f: Callable[[tree.Node], None]) -> None:
    """Apply ``f`` to every node of ``t`` whose id is ``node_id``, children first."""
    for child in t.children:
        _every_node(child, node_id, f)
    if t.id == node_id:
        f(t)


def _ins(t: tree.Node, parent: str, n: tree.Node) -> None:
    """Append a copy of ``n`` to every node carrying ``parent`` (the reference's ``ins``)."""
    _every_node(t, parent, lambda node: node.children.append(n.clone()))


def _rem_at(t: tree.Node, parent: str, x: str) -> None:
    """Drop every child carrying ``x`` from every node carrying ``parent`` (the reference's
    ``rem_at`` over ``drop_kid``)."""

    def drop(node: tree.Node) -> None:
        node.children[:] = [c for c in node.children if c.id != x]

    _every_node(t, parent, drop)


def _reorder_at(t: tree.Node, parent: str, order: tuple[str, ...]) -> None:
    """Arrange the children of every node carrying ``parent`` in ``order``: for each id of
    ``order``, the LAST child carrying it (the reference's ``Map.ofList`` keeps the last entry
    for a repeated key), an id no child carries dropped (the reference's ``reorder_at`` over
    ``arrange``)."""

    def arrange(node: tree.Node) -> None:
        last: dict[str, tree.Node] = {c.id: c for c in node.children}
        node.children[:] = [last[i] for i in order if i in last]

    _every_node(t, parent, arrange)


def _upd(t: tree.Node, x: str, kind: str) -> None:
    """Rewrite the kind of every node carrying ``x`` (the reference's ``upd``)."""

    def rewrite(node: tree.Node) -> None:
        node.kind = kind

    _every_node(t, x, rewrite)


def _same_multiset(a: list[str], b: tuple[str, ...]) -> bool:
    return Counter(a) == Counter(b)


def apply(t: tree.Node, op: Op) -> tuple[tree.Node | None, Rejection | None]:
    """Apply ``op`` to ``t``: ``(tree, None)`` on acceptance, ``(None, rejection)`` otherwise.
    ``t`` is never changed."""
    out = t.clone()
    rejection = _apply_in_place(out, op)
    if rejection is not None:
        return None, rejection
    return out, None


def _apply_in_place(t: tree.Node, op: Op) -> Rejection | None:
    """The reference's apply clause for clause, in place. On a rejection the tree may be partly
    changed (a batch member applied before the refused one); :func:`apply` is the
    all-or-nothing form."""
    if isinstance(op, InsertChild):
        dup = _first_duplicate(t, op.node)
        if dup is not None:
            return DuplicateId(dup)
        if not _has_id(t, op.parent):
            return UnknownNode(op.parent)
        _ins(t, op.parent, op.node)
        return None
    if isinstance(op, RemoveNode):
        if op.target == t.id:
            return CannotRemoveRoot()
        if not _has_id(t, op.target):
            return UnknownNode(op.target)
        pid = _parent_of(t, op.target)
        if pid is None:
            return UnknownNode(op.target)
        _rem_at(t, pid, op.target)
        return None
    if isinstance(op, MoveNode):
        if op.target == t.id:
            return CannotRemoveRoot()
        if not _has_id(t, op.target):
            return UnknownNode(op.target)
        if not _has_id(t, op.new_parent):
            return UnknownNode(op.new_parent)
        found = t.find(op.target)
        assert found is not None
        sub = found.clone()
        if _has_id(sub, op.new_parent):
            return WouldNestUnderSelf(op.target)
        pid = _parent_of(t, op.target)
        if pid is None:
            return UnknownNode(op.target)
        _rem_at(t, pid, op.target)
        if not _has_id(t, op.new_parent):
            return UnknownNode(op.new_parent)
        _ins(t, op.new_parent, sub)
        return None
    if isinstance(op, ReorderChildren):
        p = t.find(op.parent)
        if p is None:
            return UnknownNode(op.parent)
        if not _same_multiset([c.id for c in p.children], op.order):
            return ReorderMismatch(op.parent)
        _reorder_at(t, op.parent, op.order)
        return None
    if isinstance(op, Batch):
        for member in op.ops:
            rejection = _apply_in_place(t, member)
            if rejection is not None:
                return rejection
        return None
    if isinstance(op, UpdateNode):
        if not _has_id(t, op.node.id):
            return UnknownNode(op.node.id)
        _upd(t, op.node.id, op.node.kind)
        return None
    raise TypeError(f"not an op: {op!r}")
