"""The exact decimal: a value carried as its CANONICAL TEXT, never a host decimal or float — the
digits are the value, and text is the one representation every host agrees on. The twin of the
reference's ``Decimal`` (its D72), certified against the reference's ``laws/decimal-laws.json``
(the ``canonical``, ``compare``, ``add`` and ``toFloat`` cases).

THE GRAMMAR READ is ``-?[0-9]+(\\.[0-9]+)?`` over ASCII digits: a leading ``+``, a bare point
(``.5``, ``5.``), an exponent, a separator and white space are refused. THE CANONICAL FORM
WRITTEN has no leading zero on the integer part, no trailing zero on the fraction, no point
where the fraction is zero and no sign on zero, so two texts denote one number exactly when
their canonical forms are one string.

The arithmetic is exact over Python integers scaled by a power of ten. The standard library's
:mod:`decimal` is deliberately not used: its contexts and rounding are a different
specification. The only approximation is :func:`to_float`, which a caller asks for by name.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _is_ascii_digits(s: str) -> bool:
    return s != "" and all("0" <= c <= "9" for c in s)


def _parts(s: str) -> tuple[bool, str, str] | None:
    """Decimal text as ``(negative, integer digits, fraction digits)`` with the leading integer
    zeros and trailing fraction zeros stripped, or ``None`` outside the grammar."""
    if s == "":
        return None
    neg = s[0] == "-"
    body = s[1:] if neg else s
    dot = body.find(".")
    if dot < 0:
        ip, fp = body, ""
        if not _is_ascii_digits(ip):
            return None
    else:
        ip, fp = body[:dot], body[dot + 1 :]
        if not _is_ascii_digits(ip) or not _is_ascii_digits(fp):
            return None
    ip = ip.lstrip("0")
    fp = fp.rstrip("0")
    if ip == "" and fp == "":
        neg = False
    return neg, ip, fp


def canonical(s: str) -> str | None:
    """The canonical form of ``s``, or ``None`` where ``s`` is not decimal text."""
    parts = _parts(s)
    if parts is None:
        return None
    neg, ip, fp = parts
    out = ("-" if neg else "") + (ip or "0")
    if fp:
        out += "." + fp
    return out


def is_canonical(s: str) -> bool:
    """Whether ``s`` is decimal text already in its canonical form."""
    return canonical(s) == s


@dataclass(frozen=True)
class _Dec:
    """An exact value: ``unscaled × 10^-scale``, ``scale >= 0``."""

    unscaled: int
    scale: int

    def text(self) -> str:
        digits = str(abs(self.unscaled))
        if self.scale == 0:
            raw = digits
        else:
            if len(digits) <= self.scale:
                digits = "0" * (self.scale - len(digits) + 1) + digits
            raw = digits[: -self.scale] + "." + digits[-self.scale :]
        if self.unscaled < 0:
            raw = "-" + raw
        c = canonical(raw)
        assert c is not None
        return c


def _parse(s: str) -> _Dec | None:
    parts = _parts(s)
    if parts is None:
        return None
    neg, ip, fp = parts
    u = int("0" + ip + fp)
    return _Dec(-u if neg else u, len(fp))


def _aligned(a: _Dec, b: _Dec) -> tuple[int, int, int]:
    scale = max(a.scale, b.scale)
    return a.unscaled * 10 ** (scale - a.scale), b.unscaled * 10 ** (scale - b.scale), scale


def compare(a: str, b: str) -> int | None:
    """The numeric order of two decimal texts (-1 / 0 / 1), or ``None`` where either is not
    decimal text. Canonical or not: ``1.50 = 1.5``."""
    x, y = _parse(a), _parse(b)
    if x is None or y is None:
        return None
    p, q, _ = _aligned(x, y)
    return (p > q) - (p < q)


def add(a: str, b: str) -> str | None:
    """The exact sum in canonical form, or ``None`` where either is not decimal text."""
    x, y = _parse(a), _parse(b)
    if x is None or y is None:
        return None
    p, q, scale = _aligned(x, y)
    return _Dec(p + q, scale).text()


def to_float(s: str) -> float | None:
    """The nearest float to a decimal text, or ``None`` where it is not decimal text OR its
    magnitude is past the float range — an infinity is not the nearest float to any decimal.
    The one place the type rounds."""
    c = canonical(s)
    if c is None:
        return None
    f = float(c)
    if math.isinf(f):
        return None
    return f
