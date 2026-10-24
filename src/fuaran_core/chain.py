"""The op-stream chain: an append-only sequence of records, each hashing its predecessor's
hash with its own pre-image, so a tamper to any historical record breaks the chain at that
record and the walk names the first break.

The chain reads no op: every op is a string spliced into the pre-image unread, and an actor is
its canonical text (:func:`encode_actor`). So one chain serves every op vocabulary, and a host
certifies it with no op codec. ::

    payload = {"seq":<seq>,"actor":<actor>,"op":<op>}      (exactly these bytes)
    hash    = sha256Hex(prevHash ++ "|" ++ payload)          (lower-case hex)

Under the canonical profile the first record hangs from :data:`GENESIS`, the empty string, at
sequence 0; a stream that keeps another genesis (a wire's own fixed anchor) starts from an
:class:`Anchor` naming it. Certified against the reference's ``chain/skeleton-chain.json``,
and the actor and pre-image spelling against ``escape/string-escape.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from . import address, json

#: The canonical profile's genesis: the empty previous hash.
GENESIS = ""


@dataclass(frozen=True)
class Human:
    """A person or account id — the load-bearing accountability case."""

    id: str


@dataclass(frozen=True)
class Agent:
    """An AI author; ``model`` and ``version`` double as provenance metadata."""

    model: str
    version: str
    id: str


#: Who authored an op — folded into every pre-image, so attribution is tamper-evident.
type Actor = Human | Agent


def encode_actor(actor: Actor) -> str:
    """The actor's canonical text. The member order is PINNED (kind first, then the case's
    members in declaration order), not sorted: the same bytes are folded into a chain payload
    and a DAG node id, so there is one spelling to drift."""
    if isinstance(actor, Human):
        return '{"kind":"human","id":' + json.escape_string(actor.id) + "}"
    if isinstance(actor, Agent):
        return (
            '{"kind":"agent","model":'
            + json.escape_string(actor.model)
            + ',"version":'
            + json.escape_string(actor.version)
            + ',"id":'
            + json.escape_string(actor.id)
            + "}"
        )
    raise TypeError(f"not an actor: {actor!r}")


def parse_actor(text: str) -> Actor:
    """An actor from its canonical text; a text that is not an actor's raises ``ValueError``."""
    value, refusal = json.try_parse(text)
    if refusal is not None or not isinstance(value, dict):
        raise ValueError(f"not an actor: {text}")
    kind = value.get("kind")
    actor: Actor
    if kind == "human" and isinstance(value.get("id"), str):
        actor = Human(value["id"])
    elif kind == "agent" and all(isinstance(value.get(k), str) for k in ("model", "version", "id")):
        actor = Agent(value["model"], value["version"], value["id"])
    else:
        raise ValueError(f"not an actor: {text}")
    if encode_actor(actor) != text:
        raise ValueError(f"not an actor's canonical text: {text}")
    return actor


def payload(seq: int, actor: str, op: str) -> str:
    """The pre-image of the record at ``seq``: the actor and the op spliced verbatim."""
    return '{"seq":' + str(seq) + ',"actor":' + actor + ',"op":' + op + "}"


def link(prev_hash: str, payload_text: str) -> str:
    """The hash a record hangs from ``prev_hash`` with ``payload_text``."""
    return address.sha256_hex(prev_hash + "|" + payload_text)


@dataclass(frozen=True)
class Anchor:
    """Where the next record hangs: the hash it links to and its sequence number."""

    prev_hash: str = GENESIS
    seq: int = 0


#: The canonical profile's start: :data:`GENESIS` at sequence 0.
GENESIS_ANCHOR = Anchor()


@dataclass(frozen=True)
class Record:
    """One chained record. ``actor`` and ``op`` are canonical text, carried verbatim."""

    seq: int
    actor: str
    op: str
    prev_hash: str
    hash: str

    def payload(self) -> str:
        """The record's pre-image, recomputed from its own members."""
        return payload(self.seq, self.actor, self.op)


def append(anchor: Anchor, actor: str, op: str) -> tuple[Record, Anchor]:
    """Chain one record onto ``anchor``; the record and the anchor after it."""
    h = link(anchor.prev_hash, payload(anchor.seq, actor, op))
    return Record(anchor.seq, actor, op, anchor.prev_hash, h), Anchor(h, anchor.seq + 1)


class BreakReason(Enum):
    """Why a walk stopped, by its canonical spelling."""

    SEQUENCE_MISMATCH = "sequence-number mismatch"
    PREV_HASH_BROKEN = "prev-hash link broken"
    HASH_MISMATCH = "hash mismatch (tampered op/actor/seq)"


@dataclass(frozen=True)
class Break:
    """The first break a walk finds: the record's index in the run, the reason, and the value
    the walk expected beside the one it found."""

    index: int
    reason: BreakReason
    expected: str
    got: str


def walk(anchor: Anchor, records: list[Record]) -> tuple[Anchor | None, Break | None]:
    """Check ``records`` from ``anchor``: each record's sequence number, then its link, then
    its hash; the first fault is reported. An intact run answers the anchor the next record
    would hang from."""
    at = anchor
    for index, r in enumerate(records):
        if r.seq != at.seq:
            return None, Break(index, BreakReason.SEQUENCE_MISMATCH, str(at.seq), str(r.seq))
        if r.prev_hash != at.prev_hash:
            return None, Break(index, BreakReason.PREV_HASH_BROKEN, at.prev_hash, r.prev_hash)
        recomputed = link(r.prev_hash, r.payload())
        if recomputed != r.hash:
            return None, Break(index, BreakReason.HASH_MISMATCH, recomputed, r.hash)
        at = Anchor(r.hash, r.seq + 1)
    return at, None
