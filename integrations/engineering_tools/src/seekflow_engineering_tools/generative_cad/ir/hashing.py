"""Deterministic hashing for G-CAD documents."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_hash(obj: Any) -> str:
    """Return a stable sha256: hex digest for any JSON-serializable object."""
    data = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def graph_hash(canonical_nodes: list) -> str:
    """Compute canonical graph hash from resolved node list."""
    return stable_hash([n.model_dump() for n in canonical_nodes])


def contract_hash(contract: dict) -> str:
    return stable_hash(contract)
