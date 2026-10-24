"""Canonical JSON: the value model, the strict reader every wire's JSON layer cites, and
the canonical writer.

Every Fuaran wire is JSON below its own vocabulary, and the reference states once what
that JSON is (its "JSON-syntax layer"). A conformant document is one RFC 8259 text, read
strictly; each row below is a refusal of the TEXT, and no conformant encoder can reach one:

| Row | Input class                                                     | Refused as |
|-----|-----------------------------------------------------------------|------------|
| 1   | a repeated member name in one object, compared after unescaping | ``DuplicateMember`` |
| 2   | content after the root value                                    | ``TrailingCharacters`` |
| 3   | a number outside the RFC 8259 grammar                           | ``MalformedNumber`` (``UnexpectedChar`` where the token cannot start a value: ``+1``, ``.5``) |
| 4   | a bare ``NaN`` / ``Infinity`` / ``-Infinity``                   | ``UnexpectedChar`` (``MalformedNumber`` for ``-Infinity``, whose sign starts a number) |
| 5   | a raw C0 control character inside a string                      | ``BadEscape`` |
| 6   | an unpaired surrogate, raw or escaped                           | ``BadEscape`` |
| 7   | an overflowing exponent (``1e999``), or an integer token past 2^53 that is not the canonical layout of the double it reads as | ``MalformedNumber`` |

A quoted sentinel (``"NaN"``) is a string: what a typed float slot makes of it is the citing
wire's question, not this layer's.

Limits are a mechanism, never values. Every read takes a :class:`Limits` record and enforces
each bound ON THE WAY DOWN, before the container, code point, item or member it guards is
read, so nothing past a bound is ever read or built. A breach is a :class:`LimitBreach` at
the path of the container it was raised in, and is never reported as malformed text; the
first fault in document order wins, whichever kind it is. The values belong to each wire: a
host passes its specification's numbers and maps the breach to its own envelope.
:data:`STRICT` bounds the depth at 512, the reader's own stack guard, and nothing else.

Positions are UTF-16 code-unit offsets, the reference's string model, so a refusal's ``at``
is the reference's on every input and not only on ASCII. A Python ``str`` is a sequence of
code points: an astral code point counts two units, and a lone surrogate code point (which a
``str`` can hold) is one unit of its class, read exactly as the reference reads the unit.

The model and its answers are certified against the reference's ``refusals/`` (the ``json``
vectors), ``decode/`` and ``premises/`` families.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

# ── The value model ──────────────────────────────────────────────────────────────────
#
# A parsed value is one of: ``None`` (null), ``bool``, ``float`` (every number, read as an
# IEEE-754 double), ``str``, ``list`` (an array, in document order) or ``dict`` (an object,
# in parse order; a repeated member name never reaches it — row 1 refuses it at the reader).
#
# Reading every number as a double is conformant rather than a limitation: integer identity
# on the wire stops at ±2^53, and the bound was chosen precisely because the integer and
# float canonical layouts AGREE over that range, so re-encoding produces the integer spelling
# with no integer type in play. Past the bound row 7 admits only a token that IS the canonical
# layout of its double, so there is nothing an integer arm could preserve that a host is
# required to preserve.

type Value = None | bool | float | int | str | list["Value"] | dict[str, "Value"]

#: Where integer identity stops on the wire. Beyond this a decimal integer token has no
#: representation every host holds exactly.
PAYLOAD_INT_MAX = 9007199254740991


class ErrorKind(Enum):
    """The class of a malformed text — the reference's closed ``JsonErrorKind``, every case
    of it, so a refusal names the class the reference names. The sentence beside a refusal is
    this host's own."""

    UNEXPECTED_CHAR = "UnexpectedChar"
    UNEXPECTED_END_OF_INPUT = "UnexpectedEndOfInput"
    EXPECTED_TOKEN = "ExpectedToken"
    UNTERMINATED_STRING = "UnterminatedString"
    UNTERMINATED_ESCAPE = "UnterminatedEscape"
    TRUNCATED_UNICODE_ESCAPE = "TruncatedUnicodeEscape"
    BAD_ESCAPE = "BadEscape"
    BAD_HEX_DIGIT = "BadHexDigit"
    MALFORMED_NUMBER = "MalformedNumber"
    #: A null where the reading admits none. :func:`parse` and :func:`read` build ``None``
    #: and never raise it; the decode layer reads the reference's null-free model and does.
    NULL_NOT_REPRESENTABLE = "NullNotRepresentable"
    #: The reference's own name for its depth cap. This reader raises a depth breach as a
    #: :class:`LimitBreach` with :attr:`Limit.DEPTH`, as the reference does under a limits
    #: record; the case is kept so the vocabulary is the reference's, whole.
    MAX_DEPTH_EXCEEDED = "MaxDepthExceeded"
    TRAILING_CHARACTERS = "TrailingCharacters"
    DUPLICATE_MEMBER = "DuplicateMember"


class Limit(Enum):
    """A bound of :class:`Limits`, by the reference's member name."""

    #: The nested objects and arrays admitted, the root counting as one.
    DEPTH = "depth"
    #: The Unicode code points in ONE decoded string or member name — a surrogate pair is
    #: one, whichever spelling it arrived in.
    STRING_LENGTH = "stringLength"
    #: The items in one array.
    ARRAY_LENGTH = "arrayLength"
    #: The members in one object.
    OBJECT_MEMBERS = "objectMembers"
    #: The UTF-8 bytes of the whole input.
    DOCUMENT_BYTES = "documentBytes"


#: One step of a path from the document root: a member name or an item index.
type PathSeg = str | int


class Refusal(Exception):
    """Why a read refused: the text is malformed (:class:`JsonError`), or it is well-formed
    and passes a bound (:class:`LimitBreach`). The two are never conflated — a breach reported
    as malformed sends the author to repair the wrong thing."""

    #: The UTF-16 offset the refusal was raised at.
    at: int

    def refusal_class(self) -> str:
        """The class as the reference's vectors spell it: the malformed-text kind, or
        ``LimitExceeded/<bound>`` for a well-formed document past a bound."""
        raise NotImplementedError


@dataclass(frozen=True)
class JsonError(Refusal):
    """Malformed text: the class, the UTF-16 offset it was detected at, and a sentence."""

    kind: ErrorKind
    at: int
    message: str

    def __str__(self) -> str:
        return f"{self.kind.value} at {self.at}: {self.message}"

    def refusal_class(self) -> str:
        return self.kind.value


@dataclass(frozen=True)
class LimitBreach(Refusal):
    """A bound passed: which, its declared value, the path of the container it was raised in
    (the string's own path for a string value, the object's for a member name, the root for
    the document size), and the offset. Never the input."""

    limit: Limit
    value: int
    path: tuple[PathSeg, ...]
    at: int

    def __str__(self) -> str:
        return f"limit {self.limit.value} of {self.value} exceeded"

    def refusal_class(self) -> str:
        return "LimitExceeded/" + self.limit.value


@dataclass(frozen=True)
class Limits:
    """The bounds a read enforces on the way down. A zero bound is unbounded; the depth is
    always bounded, because it is the reader's stack guard."""

    depth: int = 512
    string_length: int = 0
    array_length: int = 0
    object_members: int = 0
    document_bytes: int = 0


#: The reader's own stack guard: nesting past 512 is refused, and no other bound applies.
#: Deliberately looser than any wire's bound, so the reader never refuses a document a wire
#: says a host must accept.
STRICT = Limits(depth=512)


# ── The reader ───────────────────────────────────────────────────────────────────────


class Builder[V](Protocol):
    """What a reading builds from the tokens. One reader serves both value models — the
    model above and the null-free, integer-aware model of :mod:`fuaran_core.decode` — so the
    grammar, the rows and the limits are stated once."""

    def null(self) -> tuple[V, bool]:
        """The null value, or ``ok`` false when the reading admits no null."""
        ...

    def boolean(self, b: bool) -> V: ...

    def number(self, n: float, integer_token: bool) -> V:
        """``integer_token`` is true for a token with no point and no exponent."""
        ...

    def string(self, s: str) -> V: ...

    def array(self, items: list[V]) -> V: ...

    def obj(self, members: list[tuple[str, V]]) -> V: ...


class _ValueBuilder:
    def null(self) -> tuple[Value, bool]:
        return None, True

    def boolean(self, b: bool) -> Value:
        return b

    def number(self, n: float, integer_token: bool) -> Value:
        return n

    def string(self, s: str) -> Value:
        return s

    def array(self, items: list[Value]) -> Value:
        return items

    def obj(self, members: list[tuple[str, Value]]) -> Value:
        return dict(members)


_VALUE_BUILDER = _ValueBuilder()


def parse(text: str) -> Value:
    """Read a document under the reader's own stack guard (:data:`STRICT`); a refusal is
    raised as a :class:`Refusal`."""
    return scan(text, STRICT, _VALUE_BUILDER)


def read(text: str, limits: Limits) -> Value:
    """Read a document under ``limits``, each bound enforced on the way down."""
    return scan(text, limits, _VALUE_BUILDER)


def try_parse(text: str) -> tuple[Value, Refusal | None]:
    """:func:`parse` answering the refusal instead of raising it."""
    try:
        return parse(text), None
    except Refusal as r:
        return None, r


def utf8_length(text: str) -> int:
    """The UTF-8 byte length of a text, a lone surrogate code point counted as its three
    WTF-8 bytes (so the measure is total)."""
    return len(text.encode("utf-8", errors="surrogatepass"))


def scan[V](text: str, limits: Limits, build: Builder[V]) -> V:
    """Read the whole document under ``limits`` through ``build``: the document bound before
    anything is read, then exactly ONE value and nothing after it but whitespace (row 2)."""
    if limits.document_bytes > 0 and utf8_length(text) > limits.document_bytes:
        raise LimitBreach(Limit.DOCUMENT_BYTES, limits.document_bytes, (), 0)
    parser = _Parser(text, limits, build)
    # The reader descends once per level, two Python frames a level, and refuses past the
    # depth bound before it descends. CPython's pure-Python frames live on the heap, so the
    # recursion limit is the only stack this reader has, and it is raised to hold the bound
    # it enforces rather than inherited unknowingly (the premise the recursion-depth probe
    # discharges on this runtime).
    needed = 2 * limits.depth + 64
    previous = sys.getrecursionlimit()
    raised = previous < needed
    if raised:
        sys.setrecursionlimit(needed)
    try:
        try:
            value = parser.parse_value()
        except LimitBreach as breach:
            # Pushed inner-first on the way out; reversed once here.
            raise LimitBreach(
                breach.limit, breach.value, tuple(reversed(breach.path)), breach.at
            ) from None
        parser.skip_ws()
        if parser.pos < len(text):
            raise parser.fail(
                ErrorKind.TRAILING_CHARACTERS,
                "content after the root value (the JSON-syntax layer, row 2)",
            )
        return value
    finally:
        if raised:
            sys.setrecursionlimit(previous)


def _is_digit(c: str) -> bool:
    return "0" <= c <= "9"


def _is_hex(c: str) -> bool:
    return _is_digit(c) or "a" <= c <= "f" or "A" <= c <= "F"


_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}

# Surrogate classes of one appended unit.
_NO_SUR = 0  # a code point of its own
_HI_SUR = 1  # a high half, waiting for its low half
_LO_SUR = 2  # a low half, completing a high half


def _surrogate_class(cp: int) -> int:
    if 0xD800 <= cp <= 0xDBFF:
        return _HI_SUR
    if 0xDC00 <= cp <= 0xDFFF:
        return _LO_SUR
    return _NO_SUR


def _units(cp: int) -> int:
    """The UTF-16 units one code point occupies."""
    return 2 if cp > 0xFFFF else 1


class _Parser[V]:
    __slots__ = ("build", "depth", "limits", "pos", "src")

    def __init__(self, src: str, limits: Limits, build: Builder[V]) -> None:
        self.src = src
        self.pos = 0  # a code-point index into src
        # Containers open, counted on the way DOWN, before the recursion that would pass the
        # bound. Without it the reader is unbounded mutual recursion.
        self.depth = 0
        self.limits = limits
        self.build = build

    # ── positions ──

    def at(self, pos: int | None = None) -> int:
        """The UTF-16 offset of code-point index ``pos`` (the cursor's by default)."""
        if pos is None:
            pos = self.pos
        return pos + sum(1 for ch in self.src[:pos] if ord(ch) > 0xFFFF)

    def fail(self, kind: ErrorKind, message: str, pos: int | None = None) -> JsonError:
        return JsonError(kind, self.at(pos), message)

    def breach(self, limit: Limit, value: int) -> LimitBreach:
        return LimitBreach(limit, value, (), self.at())

    # ── grammar ──

    def skip_ws(self) -> None:
        src, pos = self.src, self.pos
        while pos < len(src) and src[pos] in " \t\n\r":
            pos += 1
        self.pos = pos

    def expect(self, ch: str) -> None:
        """Consume ``ch``, or refuse ``ExpectedToken`` where the cursor stands — at the end
        of the input too, as the reference's ``expect`` does; ``UnexpectedEndOfInput`` is
        raised only where a VALUE was expected and the input ended."""
        if self.pos >= len(self.src):
            raise self.fail(ErrorKind.EXPECTED_TOKEN, f"expected '{ch}' but the input ended")
        found = self.src[self.pos]
        if found != ch:
            raise self.fail(ErrorKind.EXPECTED_TOKEN, f"expected '{ch}' but found '{found}'")
        self.pos += 1

    def parse_value(self) -> V:
        self.skip_ws()
        if self.pos >= len(self.src):
            raise self.fail(ErrorKind.UNEXPECTED_END_OF_INPUT, "unexpected end of input")
        c = self.src[self.pos]
        if c == "{" or c == "[":
            # Refused BEFORE descending: a check after the walk has already paid the cost it
            # exists to refuse, and here it would never run at all.
            if self.depth >= self.limits.depth:
                raise self.breach(Limit.DEPTH, self.limits.depth)
            self.depth += 1
            try:
                return self.parse_object() if c == "{" else self.parse_array()
            finally:
                self.depth -= 1
        if c == '"':
            return self.build.string(self.parse_string())
        if c == "t":
            return self.literal("true", lambda: self.build.boolean(True))
        if c == "f":
            return self.literal("false", lambda: self.build.boolean(False))
        if c == "n":
            # A reading that admits no null refuses at the `n`, before the literal is read,
            # as the reference's strict reading does.
            value, ok = self.build.null()
            if not ok:
                raise self.fail(
                    ErrorKind.NULL_NOT_REPRESENTABLE, "null is not representable in this reading"
                )
            return self.literal("null", lambda: value)
        if c == "-" or _is_digit(c):
            return self.parse_number()
        raise self.fail(ErrorKind.UNEXPECTED_CHAR, f"unexpected character '{c}'")

    def literal(self, word: str, value: Callable[[], V]) -> V:
        if self.src.startswith(word, self.pos):
            self.pos += len(word)
            return value()
        raise self.fail(ErrorKind.EXPECTED_TOKEN, f"expected '{word}'")

    def parse_string(self) -> str:
        """Read one string literal, as the reference's parser does, unit by unit:

        * Row 6 — an unpaired surrogate is refused. A high half must be followed IMMEDIATELY
          by a low half, and a low half must complete a pending high; the refusal fires AFTER
          the offending unit is consumed (a character after it, an escape after its letter
          or its four hex digits, the closing quote after it), which is where the reference's
          position stands.
        * Row 5 — a raw C0 control character is refused AT the character, before the
          surrogate test. A conformant encoder escapes them, so passing one through admits
          input no encoder produces.
        * The string bound, counted in CODE POINTS as the literal is built, tested after the
          surrogate tests and before the unit is appended: a low half completing a pending
          high is not a new code point. Measuring afterwards has already paid the allocation
          the bound exists to refuse.
        """
        self.expect('"')
        out: list[str] = []
        code_points = 0
        pending = False  # the last unit was a high surrogate waiting for its low half
        high = 0  # that high half
        limit = self.limits.string_length

        def unit(cp: int, cls: int) -> None:
            # The reference's `append`: the two surrogate tests, the bound, then the unit.
            nonlocal code_points, pending, high
            if pending and cls != _LO_SUR:
                raise self.fail(
                    ErrorKind.BAD_ESCAPE,
                    "an unpaired high surrogate (the JSON-syntax layer, row 6): "
                    "a high half must be followed immediately by a low half",
                )
            if not pending and cls == _LO_SUR:
                raise self.fail(
                    ErrorKind.BAD_ESCAPE,
                    "an unpaired low surrogate (the JSON-syntax layer, row 6): "
                    "a low half completes a high half before it",
                )
            if not pending:
                if limit > 0 and code_points >= limit:
                    raise self.breach(Limit.STRING_LENGTH, limit)
                code_points += 1
            if cls == _HI_SUR:
                pending, high = True, cp
            elif cls == _LO_SUR:
                out.append(chr(0x10000 + ((high - 0xD800) << 10) + (cp - 0xDC00)))
                pending = False
            else:
                out.append(chr(cp))

        src = self.src
        while True:
            if self.pos >= len(src):
                raise self.fail(ErrorKind.UNTERMINATED_STRING, "unterminated string")
            c = src[self.pos]
            if c == '"':
                self.pos += 1
                if pending:
                    raise self.fail(
                        ErrorKind.BAD_ESCAPE,
                        "an unpaired high surrogate (the JSON-syntax layer, row 6): "
                        "the string ends while a high half waits for its low half",
                    )
                return "".join(out)
            if c == "\\":
                if self.pos + 1 >= len(src):
                    raise self.fail(
                        ErrorKind.UNTERMINATED_ESCAPE, "unterminated escape", self.pos + 1
                    )
                esc = src[self.pos + 1]
                self.pos += 2
                if esc == "u":
                    u = self.parse_hex4()
                    unit(u, _surrogate_class(u))
                    continue
                simple = _SIMPLE_ESCAPES.get(esc)
                if simple is None:
                    raise self.fail(ErrorKind.BAD_ESCAPE, f"unknown escape '\\{esc}'")
                unit(ord(simple), _NO_SUR)
                continue
            cp = ord(c)
            if cp < 0x20:
                raise self.fail(
                    ErrorKind.BAD_ESCAPE,
                    f"a raw control character U+{cp:04X} inside a string (the JSON-syntax layer, row 5): "
                    "it must be escaped, and a conformant encoder escapes it",
                )
            self.pos += 1
            unit(cp, _surrogate_class(cp))

    def parse_hex4(self) -> int:
        """Read the four hex digits of a ``\\u`` escape, the cursor just past the ``\\u``. The
        reference counts the units left in UTF-16: fewer than four is
        ``TruncatedUnicodeEscape``, and four or more with one that is not a hex digit is
        ``BadHexDigit``, both refused at the first digit's position. Counting bytes or code
        points would call ``\\u0é0`` a bad digit where the reference, seeing three units,
        calls it truncated."""
        src, start = self.src, self.pos
        units = 0
        taken: list[str] = []
        i = start
        while i < len(src) and units < 4:
            units += _units(ord(src[i]))
            taken.append(src[i])
            i += 1
        if units < 4:
            raise self.fail(ErrorKind.TRUNCATED_UNICODE_ESCAPE, "truncated \\u escape")
        if len(taken) != 4 or not all(_is_hex(ch) for ch in taken):
            raise self.fail(ErrorKind.BAD_HEX_DIGIT, "bad hex digit in a \\u escape")
        self.pos = start + 4
        return int("".join(taken), 16)

    def take_digits(self) -> None:
        src, pos = self.src, self.pos
        while pos < len(src) and _is_digit(src[pos]):
            pos += 1
        self.pos = pos

    def scan_number(self) -> bool:
        """The reference's token scan: an optional sign, integer digits, an optional fraction,
        an optional exponent — each part taken as far as its characters run, whether or not
        the grammar is then met. The token ends where no part continues, so ``1e5-0`` is the
        token ``1e5`` and then trailing text, and ``01`` is one token the grammar refuses.
        Answers whether the token is a FLOAT token (a point or an exponent)."""
        src = self.src
        is_float = False
        if self.pos < len(src) and src[self.pos] == "-":
            self.pos += 1
        self.take_digits()
        if self.pos < len(src) and src[self.pos] == ".":
            self.pos += 1
            self.take_digits()
            is_float = True
        if self.pos < len(src) and src[self.pos] in "eE":
            self.pos += 1
            if self.pos < len(src) and src[self.pos] in "+-":
                self.pos += 1
            self.take_digits()
            is_float = True
        return is_float

    def parse_number(self) -> V:
        """Read one number token, held to the RFC 8259 grammar before the platform reader
        (row 3): asking ``float()`` "is this a number" asks about Python, not about this
        format. Then the two VALUE rules of row 7: a value outside the finite double range is
        refused, and an integer token past 2^53 is read only when it is the canonical layout
        of the double it reads as — judged on the TOKEN, since 2^53 + 1 reads as 2^53. Every
        refusal is at the END of the token, where the reference's position stands once the
        token is scanned."""
        start = self.pos
        is_float = self.scan_number()
        token = self.src[start : self.pos]
        if not is_rfc8259_number(token):
            raise self.fail(
                ErrorKind.MALFORMED_NUMBER,
                f"malformed number: '{token}' is not in the RFC 8259 grammar",
            )
        n = float(token)  # an underflow reads as the nearest double, an overflow as an infinity
        if math.isinf(n):
            raise self.fail(
                ErrorKind.MALFORMED_NUMBER,
                f"malformed number: '{token}' is outside the finite double range",
            )
        if not is_float and not _int53_safe_or_canonical(token, n):
            raise self.fail(
                ErrorKind.MALFORMED_NUMBER,
                f"malformed number: the integer '{token}' is past 2^53 and is not the canonical layout "
                "of a double, so it cannot round-trip",
            )
        return self.build.number(n, not is_float)

    def parse_object(self) -> V:
        self.expect("{")
        self.skip_ws()
        members: list[tuple[str, V]] = []
        seen: set[str] = set()  # the names so far: a set keeps the row-1 refusal linear in width
        src = self.src
        if self.pos < len(src) and src[self.pos] == "}":
            self.pos += 1
            return self.build.obj(members)
        limit = self.limits.object_members
        while True:
            self.skip_ws()
            if limit > 0 and len(members) >= limit:
                raise self.breach(Limit.OBJECT_MEMBERS, limit)
            key_at = self.pos
            key = self.parse_string()
            self.skip_ws()
            self.expect(":")
            try:
                value = self.parse_value()
            except LimitBreach as breach:
                raise _within(breach, key) from None
            # Row 1 — refused when the member is accumulated, after its value is read, at the
            # repeated name's opening quote. It changes what a document MEANS rather than
            # whether it is accepted: hosts kept the first or the last occurrence, so identical
            # bytes read as different documents with no error raised anywhere.
            if key in seen:
                raise self.fail(
                    ErrorKind.DUPLICATE_MEMBER,
                    f"the member '{key}' appears more than once in one object (the JSON-syntax layer, row 1)",
                    key_at,
                )
            seen.add(key)
            members.append((key, value))
            self.skip_ws()
            if self.pos < len(src) and src[self.pos] == ",":
                self.pos += 1
            elif self.pos < len(src) and src[self.pos] == "}":
                self.pos += 1
                return self.build.obj(members)
            else:
                raise self.fail(ErrorKind.EXPECTED_TOKEN, "expected ',' or '}'")

    def parse_array(self) -> V:
        self.expect("[")
        self.skip_ws()
        items: list[V] = []
        src = self.src
        if self.pos < len(src) and src[self.pos] == "]":
            self.pos += 1
            return self.build.array(items)
        limit = self.limits.array_length
        while True:
            # Where the next item would start, before a character of it is read.
            if limit > 0 and len(items) >= limit:
                self.skip_ws()
                raise self.breach(Limit.ARRAY_LENGTH, limit)
            index = len(items)
            try:
                items.append(self.parse_value())
            except LimitBreach as breach:
                raise _within(breach, index) from None
            self.skip_ws()
            if self.pos < len(src) and src[self.pos] == ",":
                self.pos += 1
            elif self.pos < len(src) and src[self.pos] == "]":
                self.pos += 1
                return self.build.array(items)
            else:
                raise self.fail(ErrorKind.EXPECTED_TOKEN, "expected ',' or ']'")


def _within(breach: LimitBreach, seg: PathSeg) -> LimitBreach:
    """Add the step the breach passed through on its way out. Only a breach carries a path;
    malformed text is refused at the root by every reading."""
    return LimitBreach(breach.limit, breach.value, breach.path + (seg,), breach.at)


def _int53_safe_or_canonical(token: str, n: float) -> bool:
    """An integer token within 2^53 in magnitude, or one past it that is the canonical float
    layout of ``n``, the double it reads as. Every other integer token past 2^53 is refused
    (row 7)."""
    digits = token.removeprefix("-")
    safe = len(digits) < 16 or (len(digits) == 16 and digits <= "9007199254740992")
    return safe or format_number(n) == token


def is_rfc8259_number(s: str) -> bool:
    """The RFC 8259 number production, exactly::

        number = [ "-" ] int [ frac ] [ exp ]
        int    = "0" / ( digit1-9 *DIGIT )
        frac   = "." 1*DIGIT
        exp    = ("e" / "E") [ "+" / "-" ] 1*DIGIT

    Written out rather than delegated, because delegating is the defect: every platform's
    float reader accepts a different superset, so a host that reaches for one accepts a set
    that is a property of its runtime rather than of JSON.
    """
    i, n = 0, len(s)
    if i < n and s[i] == "-":
        i += 1
    if i < n and s[i] == "0":
        i += 1
    elif i < n and "1" <= s[i] <= "9":
        while i < n and _is_digit(s[i]):
            i += 1
    else:
        return False
    if i < n and s[i] == ".":
        i += 1
        start = i
        while i < n and _is_digit(s[i]):
            i += 1
        if i == start:
            return False
    if i < n and s[i] in "eE":
        i += 1
        if i < n and s[i] in "+-":
            i += 1
        start = i
        while i < n and _is_digit(s[i]):
            i += 1
        if i == start:
            return False
    return i == n


# ── The writer ───────────────────────────────────────────────────────────────────────


def format_finite_double(n: float) -> str:
    """Render a finite ``float`` in the canonical number form, matching .NET
    ``Double.ToString("R", InvariantCulture)``:

    * shortest round-trip significant digits (CPython's ``repr`` shares the .NET / V8 / Go
      digit sequence — the shortest decimal that round-trips to a given double is unique, so
      every correct shortest algorithm agrees);
    * fixed-point layout iff the leading-digit base-10 exponent is in ``[-4, 16]``;
    * otherwise scientific with an uppercase ``E``, an always-present exponent sign, and a
      ≥ 2-digit zero-padded exponent;
    * negative zero collapses to ``"0"``.

    The caller must ensure ``n`` is finite. Certified against the reference's
    ``premises/float-digits.json``, every vector written and read back.
    """
    if n == 0.0:  # also collapses -0.0
        return "0"
    neg = n < 0.0
    s = repr(abs(n))  # CPython shortest round-trip digits
    e_idx = s.find("e")
    if e_idx >= 0:
        mant = s[:e_idx]
        mant_exp = int(s[e_idx + 1 :])
        dot = mant.find(".")
        if dot < 0:
            digits = mant
            exp = mant_exp + (len(mant) - 1)
        else:
            digits = mant[:dot] + mant[dot + 1 :]
            exp = mant_exp + (dot - 1)
    else:
        dot = s.find(".")
        if dot < 0:
            digits = s
            exp = len(s) - 1
        else:
            int_part, frac_part = s[:dot], s[dot + 1 :]
            if int_part == "0":
                trimmed = frac_part.lstrip("0")
                leading_zeros = len(frac_part) - len(trimmed)
                digits = trimmed
                exp = -(leading_zeros + 1)
            else:
                digits = int_part + frac_part
                exp = len(int_part) - 1
    digits = digits.rstrip("0") or "0"  # only trailing zeros can drop
    if -4 <= exp <= 16:
        if exp >= 0:
            if len(digits) <= exp + 1:
                out = digits + "0" * (exp + 1 - len(digits))
            else:
                out = digits[: exp + 1] + "." + digits[exp + 1 :]
        else:
            out = "0." + "0" * (-exp - 1) + digits
    else:
        mantissa = digits if len(digits) == 1 else digits[0] + "." + digits[1:]
        out = mantissa + "E" + ("+" if exp >= 0 else "-") + str(abs(exp)).rjust(2, "0")
    return "-" + out if neg else out


def format_number(n: float) -> str:
    """The canonical number form: finite doubles in the canonical layout, the IEEE specials as
    quoted sentinel strings, negative zero collapsed to ``0``. A Python ``int`` inside
    ±(2^53 − 1) is the integer layout; outside it a conformant encoder MUST NOT emit an
    integer token, so the value is rendered as the double it will be read back as — the floor
    beneath the specification's own instruction to carry such a value as a string."""
    if isinstance(n, bool):
        raise TypeError("a bool is not a number")
    if isinstance(n, int):
        if -PAYLOAD_INT_MAX <= n <= PAYLOAD_INT_MAX:
            return str(n)
        return format_finite_double(float(n))
    if math.isnan(n):
        return '"NaN"'
    if math.isinf(n):
        return '"Infinity"' if n > 0 else '"-Infinity"'
    return format_finite_double(n)


def escape_string(s: str) -> str:
    """Quote and escape a string the one canonical way: ``"`` and ``\\`` escaped, every control
    character U+0000–U+001F as a lower-case ``\\u00xx`` with no short form, and nothing else —
    ``/`` and non-ASCII pass through literally. The result includes the surrounding quotes.
    Certified against the reference's ``escape/string-escape.json``."""
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch < " ":
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def ordinal_key(key: str) -> bytes:
    """The sort key of the canonical member order: UTF-16 code-unit order — the reference's
    ``StringComparer.Ordinal``.

    "Ordinal" means UTF-16 code-unit order, and the distinction is observable exactly above
    the BMP: an astral key encodes to a surrogate pair beginning in U+D800–U+DBFF, so it sorts
    BELOW a U+E000–U+FFFF key that it sorts ABOVE under code-point or UTF-8-byte comparison.
    Python's native ``sorted`` on ``str`` is code-point order, so it disagrees with the
    canonical order on precisely those objects — and an object carrying both kinds of key
    then canonicalises to two different byte sequences, and two different digests, depending
    on which host encoded it.

    Big-endian UTF-16 bytes compare exactly as the code units they encode do, so the encoded
    form IS the sort key. ``surrogatepass`` keeps the function total on a lone surrogate.
    """
    return key.encode("utf-16-be", errors="surrogatepass")


def ordinal_compare(a: str, b: str) -> int:
    """The three-way form of the ordinal order: -1, 0 or 1."""
    ka, kb = ordinal_key(a), ordinal_key(b)
    return -1 if ka < kb else (1 if ka > kb else 0)


def sorted_ordinal(keys: list[str] | tuple[str, ...]) -> list[str]:
    """The keys in the canonical member order."""
    return sorted(keys, key=ordinal_key)


def render_object(fields: dict[str, str] | list[tuple[str, str]]) -> str:
    """An object from (name, rendered value) pairs: names sorted ordinally, no whitespace. Each
    value is passed through verbatim."""
    items = fields.items() if isinstance(fields, dict) else fields
    parts = [
        escape_string(k) + ":" + v for k, v in sorted(items, key=lambda kv: ordinal_key(kv[0]))
    ]
    return "{" + ",".join(parts) + "}"


def render_array(items: list[str]) -> str:
    """An array from rendered items, in source order."""
    return "[" + ",".join(items) + "]"


def render(value: Value) -> str:
    """A value's canonical bytes: names sorted ordinally, the canonical number form, the
    canonical escapes. For a canonical input, ``render(parse(x)) == x``."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return format_number(value)
    if isinstance(value, str):
        return escape_string(value)
    if isinstance(value, list):
        return render_array([render(item) for item in value])
    if isinstance(value, dict):
        return render_object([(k, render(v)) for k, v in value.items()])
    raise TypeError(f"not a JSON value: {type(value)!r}")


def field_of(value: Value, key: str) -> Value:
    """Member lookup by name on any value: ``None`` unless ``value`` is an object holding
    ``key``. A repeated name cannot occur — row 1 refuses it."""
    if isinstance(value, dict):
        return value.get(key)
    return None
