"""The op-DAG: content-addressed nodes, each an op by an actor over a set of parents. A node's
id is ::

    sha256Hex( <parent ids sorted ordinally, joined by ","> ++ "|" ++ <actor> ++ "|" ++ <op> )

over the actor's canonical text and the op's (its ``canonical()``), so the id is a function of
the parent SET and the same write deduplicates to one node. The DAG holds no state: a state is
what replaying an order of its ops from an initial state gives, with the domain's apply passed
in.

Orders are Kahn drains, the ready node with the smallest id first, so every order is total and
a function of the node set; a parent the DAG does not hold constrains nothing. Certified
against the reference's ``dag/skeleton-dag.json``.
"""

from __future__ import annotations

import bisect
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from . import address, chain, json


class Op(Protocol):
    """An op a DAG can address: its canonical text is what the id hashes."""

    def canonical(self) -> str: ...


@dataclass(frozen=True)
class Text:
    """An op held as its canonical text and nothing else."""

    text: str

    def canonical(self) -> str:
        return self.text


@dataclass(frozen=True)
class Node[O: Op]:
    """One node: its id, its parents in the order first written, its actor and op."""

    id: str
    parents: tuple[str, ...]
    actor: chain.Actor
    op: O


def _sorted_ordinal(ids: list[str] | tuple[str, ...]) -> list[str]:
    return sorted(ids, key=json.ordinal_key)


def node_id(parents: list[str] | tuple[str, ...], actor: chain.Actor, op_text: str) -> str:
    """The content id of a node of ``parents``, ``actor`` and an op of canonical text ``op_text``."""
    return address.sha256_hex(
        ",".join(_sorted_ordinal(parents)) + "|" + chain.encode_actor(actor) + "|" + op_text
    )


# ── Append faults ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EmptyParentId:
    """A parent is ``""`` — the genesis marker, not a node id (genesis is no parents)."""

    def encode(self) -> str:
        return '{"$type":"emptyParentId"}'


@dataclass(frozen=True)
class CommaInParentId:
    """A parent carries the ``,`` the id's pre-image joins parents with."""

    parent: str

    def encode(self) -> str:
        return '{"$type":"commaInParentId","parentId":' + json.escape_string(self.parent) + "}"


@dataclass(frozen=True)
class UnknownParent:
    """A parent the DAG does not hold."""

    parent: str

    def encode(self) -> str:
        return '{"$type":"unknownParent","parentId":' + json.escape_string(self.parent) + "}"


@dataclass(frozen=True)
class ContentIdCollision:
    """The id is held by a node of different content."""

    node_id: str

    def encode(self) -> str:
        return '{"$type":"contentIdCollision","nodeId":' + json.escape_string(self.node_id) + "}"


#: Why a write was refused; nothing is added.
type AppendFault = EmptyParentId | CommaInParentId | UnknownParent | ContentIdCollision


# ── Replay faults and breaks ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Cyclic:
    """The nodes a drain could not place, because they lie on or below a cycle, in id order.
    Only a hand-built or unverified load can hold one."""

    unplaced: tuple[str, ...]


@dataclass(frozen=True)
class UnknownHead:
    """A replay of a head the DAG does not hold."""

    head: str


@dataclass(frozen=True)
class Rejected[R]:
    """The domain refused the op of this node, the first in replay order."""

    node: str
    rejection: R


#: Why a replay refused.
type ReplayFault[R] = UnknownHead | Cyclic | Rejected[R]


class BreakReason(Enum):
    """Why an integrity walk stopped, by its canonical spelling."""

    CONTENT_ID_MISMATCH = "content-id mismatch (tampered node)"
    MISSING_PARENT = "missing parent"


@dataclass(frozen=True)
class Break:
    """The first integrity fault: the node, the reason, and the expected and found values (the
    recomputed id and the stored one; ``""`` and the absent parent)."""

    node: str
    reason: BreakReason
    expected: str
    got: str


# ── The DAG ──────────────────────────────────────────────────────────────────────────


class Dag[O: Op]:
    """A DAG of ops."""

    def __init__(self, nodes: list[Node[O]] | None = None) -> None:
        """An empty DAG, or one of stored nodes, their ids trusted as stored — what a load does
        before it verifies. :meth:`first_break` says whether they hold."""
        self._nodes: dict[str, Node[O]] = {n.id: n for n in nodes} if nodes else {}

    def __len__(self) -> int:
        return len(self._nodes)

    def get(self, node_id: str) -> Node[O] | None:
        return self._nodes.get(node_id)

    def append_on(
        self, actor: chain.Actor, op: O, parents: list[str] | tuple[str, ...]
    ) -> tuple[str, AppendFault | None]:
        """Append ``op`` as a child of every id in ``parents`` (none is a genesis node). The
        parents are judged in the order given, the first refusal returned: ``""``, then a
        comma-bearing id, then an id the DAG does not hold. They are stored as given; the id
        sorts them, so their order changes no id. A write identical to a held node records
        nothing and answers that node's id."""
        for p in parents:
            if p == "":
                return "", EmptyParentId()
            if "," in p:
                return "", CommaInParentId(p)
            if p not in self._nodes:
                return "", UnknownParent(p)
        text = op.canonical()
        new_id = node_id(parents, actor, text)
        existing = self._nodes.get(new_id)
        if existing is not None:
            same = (
                _sorted_ordinal(existing.parents) == _sorted_ordinal(parents)
                and existing.actor == actor
                and existing.op.canonical() == text
            )
            if same:
                return new_id, None
            return "", ContentIdCollision(new_id)
        self._nodes[new_id] = Node(new_id, tuple(parents), actor, op)
        return new_id, None

    def merge_all(
        self, actor: chain.Actor, op: O, heads: list[str] | tuple[str, ...]
    ) -> tuple[str, AppendFault | None]:
        """:meth:`append_on` over ``heads`` deduplicated and sorted ordinally."""
        return self.append_on(actor, op, _sorted_ordinal(list(dict.fromkeys(heads))))

    def heads(self) -> list[str]:
        """The nodes that are no node's parent, in id order."""
        parents = {p for n in self._nodes.values() for p in n.parents}
        return _sorted_ordinal([i for i in self._nodes if i not in parents])

    def _drain(self, keep: Callable[[str], bool]) -> tuple[list[str], list[str]]:
        """The Kahn drain over the nodes ``keep`` admits, the ready node with the smallest id
        (UTF-16 ordinal) first; a parent ``keep`` refuses constrains nothing. ``(placed,
        unplaced)``, the second in id order."""
        indeg: dict[str, int] = {}
        children: dict[str, list[str]] = {}
        for i, n in self._nodes.items():
            if not keep(i):
                continue
            held = 0
            for p in n.parents:
                if p in self._nodes and keep(p):
                    held += 1
                    children.setdefault(p, []).append(i)
            indeg[i] = held
        ready_keys: list[bytes] = []
        ready: list[str] = []
        for i, deg in indeg.items():
            if deg == 0:
                _insert_ordinal(ready_keys, ready, i)
        placed: list[str] = []
        while ready:
            i = ready.pop(0)
            ready_keys.pop(0)
            placed.append(i)
            for k in _sorted_ordinal(children.get(i, [])):
                indeg[k] -= 1
                if indeg[k] == 0:
                    _insert_ordinal(ready_keys, ready, k)
        done = set(placed)
        return placed, _sorted_ordinal([i for i in indeg if i not in done])

    def total_order(self) -> tuple[list[str], Cyclic | None]:
        """The whole DAG in one total order: parents first, the smallest ready id next."""
        placed, unplaced = self._drain(lambda _: True)
        return _ordered(placed, unplaced)

    def ranks(self) -> tuple[dict[str, int], Cyclic | None]:
        """Every node's Lamport depth: 0 with no held parent, else one past its deepest held
        parent."""
        order, cyc = self.total_order()
        if cyc is not None:
            return {}, cyc
        ranks: dict[str, int] = {}
        for i in order:
            ranks[i] = max((ranks[p] + 1 for p in self._nodes[i].parents if p in ranks), default=0)
        return ranks, None

    def ancestors_of(self, root: str) -> set[str]:
        """``root`` and every node it descends from; empty for an id the DAG does not hold."""
        seen: set[str] = set()
        stack = [root]
        while stack:
            i = stack.pop()
            if i in seen:
                continue
            n = self._nodes.get(i)
            if n is not None:
                seen.add(i)
                stack.extend(n.parents)
        return seen

    def _fold[S, R](
        self, state0: S, order: list[str], apply: Callable[[O, S], tuple[S | None, R | None]]
    ) -> tuple[S, Rejected[R] | None]:
        state = state0
        for i in order:
            nxt, rejection = apply(self._nodes[i].op, state)
            if rejection is not None:
                return state, Rejected(i, rejection)
            assert nxt is not None
            state = nxt
        return state, None

    def replay_to[S, R](
        self, state0: S, head: str, apply: Callable[[O, S], tuple[S | None, R | None]]
    ) -> tuple[S | None, ReplayFault[R] | None]:
        """Replay ``head``'s history from ``state0``: its closure in drain order, each op
        applied once; the first node the domain refuses is named. ``apply`` answers
        ``(state, None)`` or ``(None, rejection)``."""
        if head not in self._nodes:
            return None, UnknownHead(head)
        closure = self.ancestors_of(head)
        order, cyc = _ordered(*self._drain(lambda i: i in closure))
        if cyc is not None:
            return None, cyc
        state, rejected = self._fold(state0, order, apply)
        if rejected is not None:
            return None, rejected
        return state, None

    def replay_all[S, R](
        self, state0: S, apply: Callable[[O, S], tuple[S | None, R | None]]
    ) -> tuple[S | None, ReplayFault[R] | None]:
        """Replay the whole DAG from ``state0`` in :meth:`total_order`."""
        order, cyc = self.total_order()
        if cyc is not None:
            return None, cyc
        state, rejected = self._fold(state0, order, apply)
        if rejected is not None:
            return None, rejected
        return state, None

    def first_break(self) -> Break | None:
        """The first integrity fault, walking the drain order then any node on or below a cycle
        in id order: a node whose id is not its content hash, then a parent the DAG does not
        hold. ``None`` for an intact DAG."""
        placed, unplaced = self._drain(lambda _: True)
        for i in placed + unplaced:
            n = self._nodes[i]
            h = node_id(n.parents, n.actor, n.op.canonical())
            if i != h:
                return Break(i, BreakReason.CONTENT_ID_MISMATCH, h, i)
            for p in n.parents:
                if p not in self._nodes:
                    return Break(i, BreakReason.MISSING_PARENT, "", p)
        return None


def _insert_ordinal(keys: list[bytes], ids: list[str], node: str) -> None:
    key = json.ordinal_key(node)
    at = bisect.bisect_left(keys, key)
    keys.insert(at, key)
    ids.insert(at, node)


def _ordered(placed: list[str], unplaced: list[str]) -> tuple[list[str], Cyclic | None]:
    if unplaced:
        return [], Cyclic(tuple(unplaced))
    return placed, None
