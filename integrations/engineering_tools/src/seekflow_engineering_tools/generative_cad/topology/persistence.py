"""Topology sidecar persistence — serialize/deserialize registry state.

Sidecar format: <part>.topology.json
Referenced from MetadataProofV4 (future).
Phase 1: core read/write with SHA256 integrity.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

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

    # Detect runtime versions for reproducibility
    try:
        import cadquery as cq
        cq_ver = getattr(cq, "__version__", "unknown")
    except ImportError:
        cq_ver = "unknown"

    sidecar = {
        "schema": "gcad_topology_v2",
        "document_id": document_id,
        "canonical_graph_hash": canonical_graph_hash,
        "topology_registry_hash": registry_hash,

        "versions": {
            "topology_algorithm": topology_algorithm_version,
            "runtime": runtime_version,
            "cadquery": cq_ver,
            "occt": occt_version,
        },

        "contracts": contracts,

        "entities": entities_list,

        "lineage": _extract_lineage(entities_list),

        "named_sets": _extract_named_sets(entities_list),

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
        "topology_schema_version": "gcad_topology_v2",
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
    if schema not in ("gcad_topology_v1", "gcad_topology_v2"):
        raise ValueError(
            f"Unsupported topology sidecar schema: {schema!r}. "
            f"Expected: 'gcad_topology_v1' or 'gcad_topology_v2'."
        )

    # PR 10: Validate registry hash
    expected_hash = data.get("topology_registry_hash", "")
    if expected_hash:
        computed_hash = _compute_snapshot_hash(data.get("entities", []))
        if computed_hash != expected_hash:
            raise ValueError(
                f"Topology sidecar registry hash mismatch: "
                f"expected={expected_hash}, computed={computed_hash}. "
                f"The sidecar may be corrupted or tampered."
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


def _extract_named_sets(entities: list[dict]) -> dict[str, list[str]]:
    """Extract named sets from entity semantic_roles for sidecar."""
    sets: dict[str, list[str]] = {}
    for ent in entities:
        role = ent.get("semantic_role", "")
        if not role:
            continue
        # Group by role prefix (e.g., "extrude/end_cap_positive" → "extrude/end_cap")
        prefix = "/".join(role.split("/")[:2]) if "/" in role else role
        if prefix not in sets:
            sets[prefix] = []
        sets[prefix].append(ent.get("persistent_id", ""))
    return sets


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


def rebind_after_restore(
    registry: TopologyRegistry,
    object_store: Any = None,
    binding_service: Any = None,
) -> dict:
    """V3: After sidecar restore + rebuild, rebind entities to actual shapes.

    All active entities are reset to 'unresolved' status with binding_state=UNBOUND.
    If the entity has an identity_descriptor (V3), it is preserved for
    descriptor-based key verification during rebuild.

    Callers should then rebuild geometry, and for each operation,
    re-verify locators using ShapeBindingService.

    Returns rebind status: {total, reset_to_unresolved, remaining_active, requires_rebuild}
    """
    unresolved = 0
    active = 0
    total = 0
    with_descriptor = 0

    for pid, rec in list(registry._entities.items()):
        total += 1
        if rec.status == "active":
            # Reset to pending — must be re-verified during rebuild
            rec.status = "unresolved"
            rec.current_locator = None
            # V3: set binding state to UNBOUND
            if hasattr(rec, 'binding_state') and rec.binding_state is not None:
                from seekflow_engineering_tools.generative_cad.topology.models import (
                    BindingState,
                )
                rec.binding_state = BindingState.UNBOUND
            # V3: preserve identity descriptor for key verification
            if getattr(rec, 'identity_descriptor', None) is not None:
                with_descriptor += 1
            rec.evidence.append({
                "event": "sidecar_restored_pending_rebind",
                "has_identity_descriptor": (
                    getattr(rec, 'identity_descriptor', None) is not None
                ),
            })
            unresolved += 1
        elif rec.status == "deleted":
            pass  # Deleted entities stay deleted
        elif rec.status == "superseded":
            pass  # Superseded entities stay superseded

    for pid in list(registry._entities.keys()):
        rec = registry._entities.get(pid)
        if rec and rec.status == "active":
            active += 1

    return {
        "total": total,
        "reset_to_unresolved": unresolved,
        "remaining_active": active,
        "requires_rebuild": unresolved > 0,
        "entities_with_descriptor": with_descriptor,  # V3: how many have recoverable identities
    }
