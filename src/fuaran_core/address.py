"""The digest and the content address: SHA-256 as lower-case hex, and ``sha256:`` with the hex
SHA-256 of a value's canonical bytes — the digest convention every reference vector and record
uses.

The digest is the standard library's :mod:`hashlib`, FIPS 180-4 on every input length; the
host-premise probe ``premises/sha256.json`` discharges that on this runtime rather than
assuming it.
"""

from __future__ import annotations

import hashlib
import math
from enum import Enum

from . import json

#: Names the digest algorithm.
PREFIX = "sha256:"


def sha256_hex(payload: str) -> str:
    """The SHA-256 of the UTF-8 bytes of ``payload`` as 64 lower-case hex digits."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Fault(Enum):
    """Why a value or a text has no content address."""

    #: The value holds a non-finite number, which has no canonical form.
    NON_FINITE = "the value holds a non-finite number, which has no canonical form"
    #: The text is not the canonical form of the value it reads as, so its digest would not
    #: recompute from that value.
    NOT_CANONICAL = "the text is not the canonical form of the value it reads as"


class AddressError(Exception):
    def __init__(self, fault: Fault) -> None:
        super().__init__(fault.value)
        self.fault = fault


def of_bytes(canonical: str) -> str:
    """The address of exactly these bytes, which the caller vouches are canonical."""
    return PREFIX + sha256_hex(canonical)


def of_value(value: json.Value) -> str:
    """The address of a value: the digest of its canonical bytes; :class:`AddressError` on a
    non-finite number."""
    if not _finite(value):
        raise AddressError(Fault.NON_FINITE)
    return of_bytes(json.render(value))


def of_canonical_text(text: str) -> str:
    """The address of a text that must already be canonical: refused when it is not, rather
    than silently re-rendered, because a re-rendered digest names bytes the caller never
    held."""
    value, refusal = json.try_parse(text)
    if refusal is not None or json.render(value) != text:
        raise AddressError(Fault.NOT_CANONICAL)
    return of_bytes(text)


def _finite(value: json.Value) -> bool:
    if isinstance(value, float):
        return not (math.isnan(value) or math.isinf(value))
    if isinstance(value, list):
        return all(_finite(item) for item in value)
    if isinstance(value, dict):
        return all(_finite(item) for item in value.values())
    return True
