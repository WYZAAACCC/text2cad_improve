"""Canonical sidecar serialization — §3 of the supplementary spec.

Provides deterministic ordering and integrity hashing for sidecar JSON:
  - canonicalize_entities: sort by persistent_id
  - canonicalize_relations: sort by canonical tuple
  - canonicalize_float: quantize and reject NaN/Infinity
  - compute_integrity_hash: SHA-256 of canonical JSON
  - canonicalize_sidecar: produce fully deterministic sidecar dict

Ensures byte-identical output across processes for the same topology state.
This is the foundation for cross-process rebind (§3.1) and tamper detection.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §3
"""

from __future__ import annotations

import hashlib
import json
import math


# ═══════════════════════════════════════════════════════════════════════════════
# Float canonicalization
# ═══════════════════════════════════════════════════════════════════════════════


def canonicalize_float(value: float, precision: int = 6) -> float:
    """Quantize a float to the given decimal precision.

    Rejects NaN and Infinity — these have no canonical representation
    and must never appear in a sidecar.

    Args:
        value: Float value to quantize.
        precision: Number of decimal places (default 6).

    Returns:
        Rounded float value.

    Raises:
        ValueError: If value is NaN or Infinity.
    """
    if math.isnan(value):
        raise ValueError("Sidecar cannot contain NaN values")
    if math.isinf(value):
        raise ValueError("Sidecar cannot contain Infinity values")
    return round(value, precision)


# ═══════════════════════════════════════════════════════════════════════════════
# Canonical ordering
# ═══════════════════════════════════════════════════════════════════════════════


def canonicalize_entities(entities: list[dict]) -> list[dict]:
    """Sort entities by persistent_id for deterministic ordering.

    This ensures that two registries with the same set of entities
    (but different insertion order) produce the same sidecar.
    """
    return sorted(entities, key=lambda e: e.get("persistent_id", ""))


def canonicalize_relations(relations: list[dict]) -> list[dict]:
    """Sort relations by canonical tuple: (relation, sorted_sources, sorted_results).

    Deduplicates identical relations.
    """
    seen: set[tuple] = set()
    result: list[dict] = []
    for r in sorted(relations, key=_relation_sort_key):
        key = _relation_sort_key(r)
        if key not in seen:
            seen.add(key)
            result.append(r)
    return result


def _relation_sort_key(r: dict) -> tuple:
    """Generate a deterministic sort key for a topology relation dict."""
    src = tuple(sorted(r.get("source_ids", [])))
    res = tuple(sorted(r.get("result_entity_keys", [])))
    return (r.get("relation", ""), src, res)


def canonicalize_lineage_edges(edges: list[dict]) -> list[dict]:
    """Sort lineage edges by (source, target) and deduplicate."""
    seen: set[tuple] = set()
    result: list[dict] = []
    for e in sorted(edges, key=lambda x: (x.get("source", ""), x.get("target", ""))):
        key = (e.get("source", ""), e.get("target", ""))
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Integrity hash
# ═══════════════════════════════════════════════════════════════════════════════


def compute_integrity_hash(sidecar: dict, prev_hash: str = "") -> str:
    """Compute SHA-256 integrity hash of the sidecar content.

    The hash covers:
      - entities list (sorted by PID)
      - lineage edges (sorted + deduplicated)
      - document_lineage_id
      - canonical_graph_hash
      - prev_hash (for chain integrity across rebuilds)

    Fields NOT covered (version metadata that may legitimately change):
      - versions (cadquery, occt, runtime)
      - contracts (may evolve across compatible versions)

    Args:
        sidecar: The canonicalized sidecar dict.
        prev_hash: Previous sidecar's integrity hash (for chain).

    Returns:
        Hex-encoded SHA-256 digest.
    """
    hasher = hashlib.sha256()
    # Hash the identity-relevant fields in deterministic order
    hasher.update(sidecar.get("document_lineage_id", "").encode())
    hasher.update(sidecar.get("canonical_graph_hash", "").encode())
    hasher.update(prev_hash.encode())

    for ent in sidecar.get("entities", []):
        pid = ent.get("persistent_id", "")
        hasher.update(pid.encode())

    for edge in sidecar.get("lineage", []):
        hasher.update(edge.get("source", "").encode())
        hasher.update(edge.get("target", "").encode())

    return hasher.hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# Full canonicalization
# ═══════════════════════════════════════════════════════════════════════════════


def canonicalize_sidecar(sidecar: dict, prev_hash: str = "") -> dict:
    """Produce a fully canonicalized sidecar dict.

    1. Sort entities by persistent_id
    2. Sort and deduplicate lineage edges
    3. Sort unresolved/ambiguous lists
    4. Compute integrity hash

    The returned dict has all collections in deterministic order,
    suitable for byte-identical JSON serialization.
    """
    result = dict(sidecar)  # shallow copy

    if "entities" in result:
        result["entities"] = canonicalize_entities(result["entities"])

    if "lineage" in result:
        result["lineage"] = canonicalize_lineage_edges(result["lineage"])

    if "unresolved" in result:
        result["unresolved"] = sorted(set(result["unresolved"]))

    if "ambiguous" in result:
        result["ambiguous"] = sorted(set(result["ambiguous"]))

    if "named_sets" in result:
        for ns in result["named_sets"]:
            if "persistent_ids" in ns:
                ns["persistent_ids"] = sorted(set(ns["persistent_ids"]))

    result["integrity_hash"] = compute_integrity_hash(result, prev_hash=prev_hash)
    result["canonicalizer_version"] = "3.0.0"

    return result
