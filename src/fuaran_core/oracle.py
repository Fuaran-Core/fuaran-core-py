"""A client of the reference's oracle protocol (its ``docs/oracle-protocol.md``, protocol
1.0): the extracted proof models run as a process, one JSON request per line on its standard
input, one JSON response per line on its standard output, in order. A host's fuzzer asks the
models about inputs nobody chose and compares each answer with its own port, which is the
differential the host-compliance class ``oracle-differential`` records.

The client belongs in test and fuzz tooling only, never on a host's runtime surface. It is a
module of the package rather than a test helper so a Python host built on this spine can drive
the same oracle against its own code.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Self

from . import json


@dataclass(frozen=True)
class OracleError(Exception):
    """The oracle's error shape: no model answered. ``code`` is one of ``malformed-request``,
    ``unknown-function``, ``bad-input`` or ``internal``, and a harness counts each as "no
    verdict", never as a disagreement."""

    code: str
    message: str

    def __str__(self) -> str:
        return f"oracle {self.code}: {self.message}"


class OracleUnavailable(Exception):
    """A dead process or an unreadable line — never a verdict."""


class Client:
    """One oracle process, serving requests in order until :meth:`close`."""

    def __init__(self, argv: list[str]) -> None:
        """Launch the oracle as the command given (the self-contained binary, or ``dotnet
        <fuaran-core-oracle.dll>`` when running from a Core checkout)."""
        if not argv:
            raise OracleUnavailable("an empty command line")
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=1 << 20,
        )
        self._closed = False

    @classmethod
    def from_command_line(cls, line: str) -> Client:
        """Split a command line (the shape an environment variable carries) and start it."""
        return cls(shlex.split(line))

    def close(self) -> None:
        """End the oracle's input and wait for it to exit."""
        if self._closed:
            return
        self._closed = True
        assert self._proc.stdin is not None
        self._proc.stdin.close()
        self._proc.wait(timeout=30)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def call(self, fn: str, input_json: str) -> json.Value:
        """Ask ``fn`` of the oracle with ``input_json`` (the request's ``input`` member, in
        canonical JSON text) and answer the ``answer`` member as a parsed value. A protocol
        error is an :class:`OracleError`; anything else is :class:`OracleUnavailable`."""
        if self._closed:
            raise OracleUnavailable("closed")
        assert self._proc.stdin is not None and self._proc.stdout is not None
        request = '{"fn":' + json.escape_string(fn) + ',"input":' + input_json + "}\n"
        try:
            self._proc.stdin.write(request.encode("utf-8"))
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
        except (OSError, ValueError) as e:
            raise OracleUnavailable(f"writing a request: {e}") from e
        if not line:
            raise OracleUnavailable("no response")
        text = tolerate_lone_surrogates(line.decode("utf-8").rstrip("\r\n"))
        value, refusal = json.try_parse(text)
        if refusal is not None:
            raise OracleUnavailable(f"a response that is not JSON: {refusal}")
        error = json.field_of(value, "error")
        if isinstance(error, dict):
            raise OracleError(str(error.get("code", "")), str(error.get("message", "")))
        answer = json.field_of(value, "answer")
        if answer is None:
            raise OracleUnavailable("a response with neither answer nor error")
        return answer

    def describe(self) -> str:
        """Ask ``oracle.describe`` and answer the protocol version it serves."""
        answer = self.call("oracle.describe", "{}")
        protocol = json.field_of(json.field_of(answer, "description"), "protocol")
        if not isinstance(protocol, str):
            raise OracleUnavailable("describe answered no protocol")
        return protocol


def _escape_at(line: str, i: int) -> int | None:
    if i + 6 > len(line) or line[i] != "\\" or line[i + 1] != "u":
        return None
    try:
        return int(line[i + 2 : i + 6], 16)
    except ValueError:
        return None


def tolerate_lone_surrogates(line: str) -> str:
    """Rewrite each UNPAIRED surrogate escape in a response line to U+FFFD. The protocol lets a
    response carry one (the oracle's string model is UTF-16 units, so a refusal's message can
    quote half of a character), and the spine's reader refuses it as every conformant reader
    must; a client has no use for the unit itself, only for the members around it."""
    out: list[str] = []
    i = 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line) and line[i + 1] != "u":
            # A short escape, copied whole, so the character after an escaped backslash is
            # never read as the start of an escape.
            out.append(line[i : i + 2])
            i += 2
            continue
        u = _escape_at(line, i)
        if u is None:
            out.append(line[i])
            i += 1
            continue
        if 0xD800 <= u <= 0xDBFF:
            low = _escape_at(line, i + 6)
            if low is not None and 0xDC00 <= low <= 0xDFFF:
                out.append(line[i : i + 12])
                i += 12
                continue
            out.append("�")
        elif 0xDC00 <= u <= 0xDFFF:
            out.append("�")
        else:
            out.append(line[i : i + 6])
        i += 6
    return "".join(out)
