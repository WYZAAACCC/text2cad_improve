"""Topology sidecar persistence — serialize/deserialize registry state.

Sidecar format: <part>.topology.json
Referenced from MetadataProofV4 (future).
Phase 1: core read/write with SHA256 integrity.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry


def write_topology_sidecar(
    registry: TopologyRegistry,
    path: Path,
    *,
    document_id: str,
    canonical_graph_hash: str,
    runtime_version: str,
    occt_version: str = "unknown",
    topology_algorithm_version: str = "1",
) -> dict:
    """Write topology sidecar JSON and return sidecar metadata.

    The returned dict is suitable for inclusion in MetadataProofV4.topology.
    It contains paths, hashes, and version info needed for artifact validation.

    Args:
        registry: The TopologyRegistry to snapshot.
        path: Output path for <part>.topology.json.
        document_id: Matches CanonicalGcadDocument.document_id.
        canonical_graph_hash: Matches CanonicalGcadDocument.canonical_graph_hash.
        runtime_version: Runner version (from ctx.runner_version).
        occt_version: OCCT library version for reproducibility.
        topology_algorithm_version: Semver of the naming algorithm.

    Returns:
        dict with topology metadata for MetadataProofV4.
    """
    snapshot = registry.export_snapshot()

    entities_list = list(snapshot["entities"].values())
    registry_hash = _compute_snapshot_hash(entities_list)

    # Extract contract entries from entity evidence
    contracts: list[dict] = []
    seen_nodes: set[str] = set()
    for ent in entities_list:
        nid = ent.get("producer_node_id", "")
        if nid and nid not in seen_nodes:
            seen_nodes.add(nid)
            contracts.append({
                "node_id": nid,
                # topology_contract_hash filled in Phase 2+
                "topology_contract_hash": "",
            })

    sidecar = {
        "schema": "gcad_topology_v1",
        "document_id": document_id,
        "canonical_graph_hash": canonical_graph_hash,
        "topology_registry_hash": registry_hash,

        "runtime": {
            "geometry_runtime": "cadquery",
            "runtime_version": runtime_version,
            "occt_version": occt_version,
            "topology_algorithm_version": topology_algorithm_version,
        },

        "contracts": contracts,

        "entities": entities_list,

        "lineage": _extract_lineage(entities_list),

        "semantic_sets": {},

        "unresolved": [
            ent["persistent_id"] for ent in entities_list
            if ent.get("status") == "unresolved"
        ],
        "ambiguous": [
            ent["persistent_id"] for ent in entities_list
            if ent.get("status") == "ambiguous"
        ],
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return {
        "topology_schema_version": "gcad_topology_v1",
        "topology_sidecar_path": str(path),
        "topology_sidecar_sha256": _compute_file_hash(path),
        "topology_registry_hash": registry_hash,
        "entity_count": len(entities_list),
        "active_count": sum(1 for e in entities_list if e.get("status") == "active"),
        "deleted_count": sum(1 for e in entities_list if e.get("status") == "deleted"),
    }


def read_topology_sidecar(
    path: Path, registry: TopologyRegistry,
) -> dict:
    """Read a topology sidecar and restore registry state.

    Args:
        path: Path to <part>.topology.json.
        registry: TopologyRegistry to restore into (cleared first).

    Returns:
        dict with sidecar metadata for validation.

    Raises:
        ValueError: If schema version is unsupported.
        FileNotFoundError: If path doesn't exist.
        json.JSONDecodeError: If file is malformed.
    """
    data = json.loads(path.read_text(encoding="utf-8"))

    schema = data.get("schema", "")
    if schema != "gcad_topology_v1":
        raise ValueError(
            f"Unsupported topology sidecar schema: {schema!r}. "
            f"Expected: 'gcad_topology_v1'."
        )

    # Rebuild snapshot-compatible dict
    entities_dict: dict[str, dict] = {}
    for ent in data.get("entities", []):
        pid = ent.get("persistent_id", "")
        if pid:
            entities_dict[pid] = ent

    snapshot = {
        "entities": entities_dict,
        "node_index": data.get("node_index", {}),
        "event_count": data.get("event_count", 0),
    }
    registry.restore_snapshot(snapshot)

    return {
        "topology_schema_version": schema,
        "topology_registry_hash": data.get("topology_registry_hash", ""),
        "entity_count": len(entities_dict),
    }


def _compute_snapshot_hash(entities: list[dict]) -> str:
    """Deterministic hash of entity list for integrity verification."""
    payload = json.dumps(entities, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _compute_file_hash(path: Path) -> str:
    """SHA256 of a file for artifact integrity."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _extract_lineage(entities: list[dict]) -> list[dict]:
    """Extract lineage edges from entity records for sidecar visualization."""
    edges: list[dict] = []
    for ent in entities:
        pid = ent.get("persistent_id", "")
        for ancestor in ent.get("ancestor_ids", []):
            edges.append({
                "from": ancestor, "to": pid,
                "relation": "derived_from",
            })
        for descendant in ent.get("descendant_ids", []):
            edges.append({
                "from": pid, "to": descendant,
                "relation": "parent_of",
            })
    return edges
