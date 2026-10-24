"""The premise legs certify the spine's runtime premises against the probes the reference emits
(``conformance/premises/``): each family is the probe a host-premise row of the reference's
claims ladder names, and reproducing every vector discharges that premise on this runtime (the
reference's ``docs/host-premises.md``). Each leg asserts it ran exactly the count the family's
manifest declares."""

from __future__ import annotations

import hashlib
import struct

import pytest
from conftest import Vectors, arr, get, n, s

from fuaran_core import decode, json


def utf8_of_units(units: list[int]) -> tuple[bytes | None, int, int]:
    """The mapping by which a sequence of UTF-16 code units reaches a Python ``str`` and its
    UTF-8: a well-formed sequence becomes its bytes, and the first unpaired surrogate refuses
    at its index. ``str.encode('utf-16')`` would raise without the index, so the pairing is
    checked here."""
    out: list[str] = []
    i = 0
    while i < len(units):
        u = units[i]
        if 0xD800 <= u <= 0xDBFF:
            if i + 1 < len(units) and 0xDC00 <= units[i + 1] <= 0xDFFF:
                out.append(chr(0x10000 + ((u - 0xD800) << 10) + (units[i + 1] - 0xDC00)))
                i += 2
                continue
            return None, i, u
        if 0xDC00 <= u <= 0xDFFF:
            return None, i, u
        out.append(chr(u))
        i += 1
    return "".join(out).encode("utf-8"), 0, 0


def test_premise_string_model(vectors: Vectors) -> None:
    ran = 0
    for v in vectors.family("premises", "string-model.json", "premiseStringModel"):
        vector_id, expected = s(v, "id"), get(v, "expected")
        if vector_id.startswith("encode/"):
            units = [int(u) for u in arr(v, "units") if isinstance(u, float)]
            encoded, index, unit = utf8_of_units(units)
            if encoded is not None:
                assert encoded.hex() == s(expected, "utf8"), vector_id
            else:
                refused = get(expected, "refused")
                assert (index, unit) == (int(n(refused, "index")), int(n(refused, "unit"))), (
                    vector_id
                )
        elif vector_id.startswith("parse/"):
            value, refusal = json.try_parse(s(v, "text"))
            if refusal is not None:
                assert refusal.refusal_class() == s(expected, "refused"), f"{vector_id}: {refusal}"
            elif isinstance(value, str):
                assert value.encode("utf-8").hex() == s(expected, "utf8"), vector_id
            elif isinstance(value, dict):
                assert len(value) == 1, vector_id
                assert next(iter(value)).encode("utf-8").hex() == s(get(expected, "key"), "utf8"), (
                    vector_id
                )
            else:
                raise AssertionError(f"{vector_id}: read {json.render(value)}")
        else:
            raise AssertionError(f"{vector_id}: an unknown probe")
        ran += 1
    assert ran == 29


def float_from_bits(hex_bits: str) -> float:
    return struct.unpack(">d", bytes.fromhex(hex_bits))[0]


def bits_of_float(f: float) -> str:
    return struct.pack(">d", f).hex()


def test_premise_float_digits(vectors: Vectors) -> None:
    ran = 0
    for v in vectors.family("premises", "float-digits.json", "premiseFloatDigits"):
        vector_id, bits = s(v, "id"), s(v, "bits")
        canonical = s(get(v, "expected"), "canonical")
        f = float_from_bits(bits)
        assert json.format_finite_double(f) == canonical, (
            f"{vector_id}: written {json.format_finite_double(f)}"
        )
        back = json.parse(
            canonical
        )  # read back: the same double, the negative zero reading as zero
        assert isinstance(back, float), vector_id
        assert bits_of_float(back) == ("0" * 16 if f == 0 else bits), (
            f"{vector_id}: read back {bits_of_float(back)}"
        )
        ran += 1
    assert ran == 163


def test_premise_int53(vectors: Vectors) -> None:
    ran = 0
    for v in vectors.family("premises", "int53.json", "premiseInt53"):
        vector_id, expected = s(v, "id"), get(v, "expected")
        try:
            value = decode.read_value(s(v, "token"), json.STRICT)
        except json.Refusal as refusal:
            assert refusal.refusal_class() == s(expected, "refused"), f"{vector_id}: {refusal}"
        else:
            if isinstance(value, int):
                assert float(value) == n(expected, "int"), f"{vector_id}: int {value}"
            elif isinstance(value, float):
                assert bits_of_float(value) == s(expected, "float"), (
                    f"{vector_id}: float {bits_of_float(value)}"
                )
            else:
                pytest.fail(f"{vector_id}: read {value!r}")
        ran += 1
    assert ran == 29


def test_premise_sha256(vectors: Vectors) -> None:
    ran = 0
    for v in vectors.family("premises", "sha256.json", "premiseSha256"):
        vector_id, inp = s(v, "id"), get(v, "input")
        message = bytes.fromhex(s(inp, "hex")) * int(n(inp, "repeat"))
        assert hashlib.sha256(message).hexdigest() == s(get(v, "expected"), "sha256"), vector_id
        ran += 1
    assert ran == 17


def test_premise_recursion_depth(vectors: Vectors) -> None:
    """The reader descends once per level and refuses past 512 before it descends; its
    pure-Python frames live on the heap and the recursion limit is raised to hold the bound,
    so a document never overflows the stack. The probes run on the main thread for that
    reason: the stack is the runtime's, stated here rather than inherited unknowingly."""
    ran = 0
    for v in vectors.family("premises", "recursion-depth.json", "premiseRecursionDepth"):
        vector_id, inp, expected = s(v, "id"), get(v, "input"), get(v, "expected")
        depth = int(n(inp, "depth"))
        text = s(inp, "open") * depth + s(inp, "inner") + s(inp, "close") * depth
        value, refusal = json.try_parse(text)
        if refusal is None:
            rendered = json.render(value)
            assert rendered == text, f"{vector_id}: the canonical rendering differs"
            assert hashlib.sha256(rendered.encode("utf-8")).hexdigest() == s(
                expected, "accepted"
            ), vector_id
        else:
            assert refusal.refusal_class() == s(expected, "refused"), f"{vector_id}: {refusal}"
        ran += 1
    assert ran == 13
