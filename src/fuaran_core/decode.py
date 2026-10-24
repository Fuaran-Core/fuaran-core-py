"""The decode error contract: the closed set of decode codes, each at the path it names, and
the reading combinators a host builds its decoders from.

A decode of JSON text has two halves. The text is read by :func:`parse`, under a
:class:`fuaran_core.json.Limits` record: malformed text is ``InvalidJson`` at the root, and a
passed bound is ``LimitExceeded`` at the path of the container it was raised in. The value is
then read through a :class:`Cursor`, whose every refusal names its code and the path from the
document root — so a decoder written over it answers exactly as the reference's decoder of the
same shape does. Certified against the reference's ``decode/decode-rejects.json``.

The value model is the reference's null-free one: a ``str``, an ``int`` (an integer token
within int32), a ``float`` (every other number), a ``bool``, a ``list`` or a ``dict`` (in
document order). A null token is refused as malformed (``NullNotRepresentable``), as the
reference's strict reading refuses it. The distinction between the two number cases is the
TOKEN's, which is why this layer reads through its own builder rather than over the json
layer's values: ``2.0`` is not an int.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from . import json

type Value = str | int | float | bool | list["Value"] | dict[str, "Value"]

_INT32_MIN, _INT32_MAX = -(2**31), 2**31 - 1


class Code(Enum):
    """One of the reference's closed set of decode codes."""

    #: The text is not one well-formed JSON document (at the root).
    INVALID_JSON = "InvalidJson"
    #: A required member is absent (at the absent member's path).
    MISSING_FIELD = "MissingField"
    #: A value of the wrong JSON kind.
    WRONG_KIND = "WrongKind"
    #: A discriminator names no case the reader knows (at the discriminator).
    UNKNOWN_TAG = "UnknownTag"
    #: A number outside its declared range.
    OUT_OF_RANGE = "OutOfRange"
    #: A member a closed object does not declare (at that member).
    UNDECLARED_MEMBER = "UndeclaredMember"
    #: A bound passed (at the container it guards).
    LIMIT_EXCEEDED = "LimitExceeded"
    #: A known case this position does not admit (at the discriminator).
    NOT_ADMITTED = "NotAdmitted"
    #: The decoder itself is ill-formed (an unresolved reference to a shape).
    SCHEMA_FAULT = "SchemaFault"


@dataclass(frozen=True)
class DecodeError(Exception):
    """A refusal: its code, the path from the document root, and a sentence."""

    code: Code
    path: tuple[json.PathSeg, ...]
    message: str

    def __str__(self) -> str:
        return f"{self.code.value} at {path_json(self.path)}: {self.message}"


def path_json(path: tuple[json.PathSeg, ...]) -> str:
    """A path as the reference's vectors carry it: a JSON array of member names and item
    indices."""
    return json.render_array(
        [json.escape_string(seg) if isinstance(seg, str) else str(seg) for seg in path]
    )


def of_refusal(r: json.Refusal) -> DecodeError:
    """The decode refusal of a refused read: malformed text is ``InvalidJson`` at the root,
    naming the parser's class; a breach is ``LimitExceeded`` at its path, naming the bound and
    its declared value."""
    if isinstance(r, json.JsonError):
        return DecodeError(Code.INVALID_JSON, (), str(r))
    if isinstance(r, json.LimitBreach):
        return DecodeError(Code.LIMIT_EXCEEDED, r.path, str(r))
    raise TypeError(f"not a refusal: {r!r}")


def kind_name(v: Value) -> str:
    """The JSON kind, as every decode error names it."""
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return "unknown"


class _ValueBuilder:
    def null(self) -> tuple[Value, bool]:
        return "", False

    def boolean(self, b: bool) -> Value:
        return b

    def number(self, n: float, integer_token: bool) -> Value:
        if integer_token and _INT32_MIN <= n <= _INT32_MAX:
            return int(n)
        return n

    def string(self, s: str) -> Value:
        return s

    def array(self, items: list[Value]) -> Value:
        return items

    def obj(self, members: list[tuple[str, Value]]) -> Value:
        return dict(members)


_VALUE_BUILDER = _ValueBuilder()


def read_value(text: str, limits: json.Limits = json.STRICT) -> Value:
    """Read JSON text under ``limits`` into the decode layer's value model, raising the
    reader's refusal whole, for a codec that projects it its own way."""
    return json.scan(text, limits, _VALUE_BUILDER)


def parse(text: str, limits: json.Limits = json.STRICT) -> Value:
    """Read JSON text under ``limits`` into the decode layer's value model; a refusal is the
    decode contract's (:func:`of_refusal`), raised as a :class:`DecodeError`."""
    try:
        return read_value(text, limits)
    except json.Refusal as r:
        raise of_refusal(r) from None


@dataclass(frozen=True)
class Cursor:
    """A value and the path that reached it. Every reading raises a :class:`DecodeError` at
    that path, or at a member or item below it."""

    value: Value
    path: tuple[json.PathSeg, ...] = ()

    @staticmethod
    def root(v: Value) -> Cursor:
        return Cursor(v, ())

    def below(self, seg: json.PathSeg, v: Value) -> Cursor:
        return Cursor(v, self.path + (seg,))

    def fail(self, code: Code, message: str) -> DecodeError:
        """A refusal at this cursor's path."""
        return DecodeError(code, self.path, message)

    def _wrong_kind(self, expected: str) -> DecodeError:
        return self.fail(Code.WRONG_KIND, f"expected {expected}, found {kind_name(self.value)}")

    def string(self) -> str:
        if isinstance(self.value, str):
            return self.value
        raise self._wrong_kind("a string")

    def int(self) -> int:
        """An integer token within int32 only: ``2.0``, ``1e3`` and an integer past int32 are
        refused as ``WrongKind``."""
        if isinstance(self.value, int) and not isinstance(self.value, bool):
            return self.value
        raise self._wrong_kind("an int")

    def float(self) -> float:
        """Any number."""
        if isinstance(self.value, int | float) and not isinstance(self.value, bool):
            return float(self.value)
        raise self._wrong_kind("a number")

    def bool(self) -> bool:
        if isinstance(self.value, bool):
            return self.value
        raise self._wrong_kind("a bool")

    def int_range(self, lo: int, hi: int) -> int:
        """An int within ``[lo, hi]``; outside it is ``OutOfRange``."""
        i = self.int()
        if i < lo or i > hi:
            raise self.fail(Code.OUT_OF_RANGE, f"{i} is outside [{lo}, {hi}]")
        return i

    def items(self) -> list[Cursor]:
        """The items of an array, each at its index."""
        if not isinstance(self.value, list):
            raise self._wrong_kind("an array")
        return [self.below(i, v) for i, v in enumerate(self.value)]

    def items_at_most(self, maximum: int) -> list[Cursor]:
        """The items of an array of at most ``maximum``; more is ``LimitExceeded`` at the
        array."""
        items = self.items()
        if len(items) > maximum:
            raise self.fail(
                Code.LIMIT_EXCEEDED, f"{len(items)} items where at most {maximum} are admitted"
            )
        return items

    def _members(self) -> dict[str, Value]:
        if isinstance(self.value, dict):
            return self.value
        raise self._wrong_kind("an object")

    def optional(self, name: str) -> Cursor | None:
        """An optional member: ``None`` when absent."""
        members = self._members()
        if name in members:
            return self.below(name, members[name])
        return None

    def field(self, name: str) -> Cursor:
        """A required member; absent is ``MissingField`` at the absent member's path."""
        at = self.optional(name)
        if at is None:
            raise self.below(name, "").fail(
                Code.MISSING_FIELD, f"the required member '{name}' is absent"
            )
        return at

    def closed(self, declared: list[str] | tuple[str, ...]) -> None:
        """A closed object: the first member, in document order, that ``declared`` does not
        name is ``UndeclaredMember`` at that member. The reference checks this before it reads
        any declared member."""
        for key, value in self._members().items():
            if key not in declared:
                raise self.below(key, value).fail(
                    Code.UNDECLARED_MEMBER, f"the member '{key}' is not declared here"
                )

    def tag(self, key: str, known: list[str] | tuple[str, ...]) -> str:
        """The discriminator of a tagged union off the SAME object as its case: absent is
        ``MissingField`` and a non-string ``WrongKind``, both at the key, and a tag outside
        ``known`` is ``UnknownTag`` there."""
        at = self.field(key)
        tag = at.string()
        if tag not in known:
            raise at.fail(Code.UNKNOWN_TAG, f"'{tag}' is not one of {', '.join(known)}")
        return tag
