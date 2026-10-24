"""The Fuaran Core spine in Python.

Canonical JSON with its proved grammar and parse limits (:mod:`fuaran_core.json`), the decode
error contract (:mod:`fuaran_core.decode`), SHA-256 content addresses
(:mod:`fuaran_core.address`), the skeleton tree and its ops (:mod:`fuaran_core.tree`,
:mod:`fuaran_core.ops`), the op-stream chain (:mod:`fuaran_core.chain`), the content-addressed
DAG (:mod:`fuaran_core.dag`) and the exact decimal (:mod:`fuaran_core.decimal`), certified
against the conformance vectors the .NET reference emits and differentially against its
extracted proof models through :mod:`fuaran_core.oracle`. Standard library only.
"""

from . import address, chain, dag, decimal, decode, json, ops, tree

__version__ = "0.0.0"

__all__ = ["address", "chain", "dag", "decimal", "decode", "json", "ops", "tree"]
