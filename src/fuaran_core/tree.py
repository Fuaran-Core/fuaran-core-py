"""The skeleton tree — the witness surface the reference's structural ops read: a node is an
id, a kind and its children, and nothing else. A host with a richer node type runs the ops by
mapping those three members onto its own node.

Its canonical bytes are ``{"children":[...],"id":...,"kind":...}`` (members sorted ordinally),
the envelope the reference's ``apply/``, ``dag/``, ``merge/`` and ``diff/`` families carry
every tree in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import decode, json


@dataclass(eq=True)
class Node:
    """A skeleton node. Equality is member for member, the whole tree."""

    id: str
    kind: str
    children: list[Node] = field(default_factory=list)

    def find(self, node_id: str) -> Node | None:
        """The FIRST node with this id in pre-order, anywhere in the tree (this node included);
        ``None`` when there is none."""
        if self.id == node_id:
            return self
        for child in self.children:
            found = child.find(node_id)
            if found is not None:
                return found
        return None

    def ids(self) -> list[str]:
        """Every id in the tree, in pre-order."""
        out: list[str] = []
        self._collect_ids(out)
        return out

    def _collect_ids(self, out: list[str]) -> None:
        out.append(self.id)
        for child in self.children:
            child._collect_ids(out)

    def clone(self) -> Node:
        """A deep copy."""
        return Node(self.id, self.kind, [child.clone() for child in self.children])

    def encode(self) -> str:
        """The node's canonical bytes."""
        out: list[str] = []
        self._encode_into(out)
        return "".join(out)

    def _encode_into(self, out: list[str]) -> None:
        out.append('{"children":[')
        for i, child in enumerate(self.children):
            if i:
                out.append(",")
            child._encode_into(out)
        out.append('],"id":')
        out.append(json.escape_string(self.id))
        out.append(',"kind":')
        out.append(json.escape_string(self.kind))
        out.append("}")


def leaf(node_id: str, kind: str) -> Node:
    """A node with no children."""
    return Node(node_id, kind, [])


def decode_node(at: decode.Cursor) -> Node:
    """Read a node: string ``id`` and ``kind`` members and a ``children`` array of nodes, each
    refusal at its path. Any other member is ignored."""
    node_id = at.field("id").string()
    kind = at.field("kind").string()
    children = [decode_node(item) for item in at.field("children").items()]
    return Node(node_id, kind, children)


def parse(text: str) -> Node:
    """Read a node from its JSON text under the reader's stack guard; a refusal is a
    :class:`fuaran_core.decode.DecodeError`."""
    return decode_node(decode.Cursor.root(decode.parse(text, json.STRICT)))
