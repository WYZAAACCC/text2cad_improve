"""Topology validation rules — plug into validation_kernel.

Phase 2: optional warning-level validation for topology contracts and references.
Phase 3+: mandatory error-level validation for topology-critical operations.

Each validation function returns a list[dict] of issues (empty = no issues).
"""

from __future__ import annotations

from typing import Any


def validate_topology_contract(
    node: Any,
    op_spec: Any,
    registry: Any | None = None,
) -> list[dict]:
    """Check that a geometry-producing operation has a topology contract.

    Phase 2: WARNING if contract is missing for geometry ops.
    Phase 3+: ERROR if contract is missing AND topology is required by consumer.

    Args:
        node: CanonicalNode with effects/op info.
        op_spec: OperationSpec for this node.
        registry: TopologyRegistry (optional, for cross-reference checks).

    Returns:
        List of issue dicts (empty = no issues).
    """
    issues = []

    # Check effects to determine if this is a geometry-producing op
    effects = getattr(op_spec, "effects", [])
    geometry_effects = {
        "creates_solid", "modifies_solid", "cuts_material",
        "adds_material", "boolean_union", "boolean_cut", "boolean_intersect",
    }

    is_geometry_op = any(e in geometry_effects for e in effects)

    if is_geometry_op:
        contract = getattr(op_spec, "topology_contract", None)
        if contract is None:
            issues.append({
                "code": "TOPOLOGY_CONTRACT_MISSING",
                "severity": "warning",
                "node_id": getattr(node, "id", "?"),
                "dialect": getattr(op_spec, "dialect", "?"),
                "op": getattr(op_spec, "op", "?"),
                "message": (
                    f"Geometry-producing operation '{getattr(op_spec, 'op', '?')}' "
                    f"has no topology contract. Persistent topology naming will be "
                    f"unavailable for faces/edges created by this operation. "
                    f"Add a TopologyContract to the OperationSpec."
                ),
            })

    return issues


def validate_topology_reference(
    node: Any,
    registry: Any | None = None,
) -> list[dict]:
    """Check that all PersistentTopoRefs in node inputs are valid.

    Phase 2: checks that referenced persistent IDs exist in registry.
    Phase 3+: checks resolution quality meets consumer policy.

    Args:
        node: CanonicalNode with potential topology references in inputs.
        registry: TopologyRegistry for resolution.

    Returns:
        List of issue dicts.
    """
    issues = []

    if registry is None:
        return issues

    # Check inputs for topology references (Phase 3+: actual PersistentTopoRef)
    for inp in getattr(node, "inputs", []):
        topo_ref = inp.get("persistent_topo_ref") if isinstance(inp, dict) else None
        if topo_ref:
            pid = topo_ref.get("persistent_id", "")
            if pid:
                rec = registry.get_entity(pid)
                if rec is None:
                    issues.append({
                        "code": "TOPOLOGY_REF_UNRESOLVED",
                        "severity": "error",
                        "node_id": getattr(node, "id", "?"),
                        "persistent_id": pid,
                        "message": f"Persistent topology reference '{pid}' not found in registry.",
                    })
                elif rec.status == "deleted":
                    issues.append({
                        "code": "TOPOLOGY_REF_DELETED",
                        "severity": "error",
                        "node_id": getattr(node, "id", "?"),
                        "persistent_id": pid,
                        "message": f"Referenced topology entity '{pid}' was deleted.",
                    })
                elif rec.status == "ambiguous":
                    issues.append({
                        "code": "TOPOLOGY_REF_AMBIGUOUS",
                        "severity": "warning",
                        "node_id": getattr(node, "id", "?"),
                        "persistent_id": pid,
                        "message": f"Referenced topology entity '{pid}' is ambiguous.",
                    })

    return issues


def validate_topology_runtime_integrity(
    registry: Any | None = None,
) -> list[dict]:
    """Check topology registry integrity post-build.

    Phase 2: basic consistency (unique IDs, no stale refs).
    Phase 3+: full lineage validation.

    Args:
        registry: TopologyRegistry to validate.

    Returns:
        List of issue dicts.
    """
    if registry is None:
        return []

    # Delegate to registry's built-in integrity check
    result = registry.validate_integrity()
    if result.get("ok"):
        return []

    return result.get("issues", [])


def validate_topology_artifact_proof(
    sidecar_path: str | None = None,
    canonical_graph_hash: str | None = None,
) -> list[dict]:
    """Check topology sidecar integrity against the build artifact.

    Phase 2: checks sidecar exists and hash matches canonical.

    Args:
        sidecar_path: Path to <part>.topology.json.
        canonical_graph_hash: Expected graph hash.

    Returns:
        List of issue dicts.
    """
    issues = []

    if sidecar_path is None:
        # Sidecar is optional in Phase 2
        return issues

    import json
    from pathlib import Path

    path = Path(sidecar_path)
    if not path.exists():
        issues.append({
            "code": "TOPOLOGY_SIDECAR_MISSING",
            "severity": "warning",
            "message": f"Topology sidecar not found: {sidecar_path}",
        })
        return issues

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        issues.append({
            "code": "TOPOLOGY_SIDECAR_INVALID",
            "severity": "error",
            "message": f"Topology sidecar is invalid JSON: {exc}",
        })
        return issues

    if canonical_graph_hash:
        sidecar_hash = data.get("canonical_graph_hash", "")
        if sidecar_hash != canonical_graph_hash:
            issues.append({
                "code": "TOPOLOGY_SIDECAR_HASH_MISMATCH",
                "severity": "error",
                "message": (
                    f"Topology sidecar canonical_graph_hash ({sidecar_hash}) "
                    f"does not match artifact ({canonical_graph_hash})"
                ),
            })

    # Check schema version
    schema = data.get("schema", "")
    if schema not in ("gcad_topology_v1", "gcad_topology_v2", "gcad_topology_v3"):
        issues.append({
            "code": "TOPOLOGY_SIDECAR_SCHEMA_UNSUPPORTED",
            "severity": "warning",
            "message": (
                f"Topology sidecar schema '{schema}' is not 'gcad_topology_v1'. "
                f"Topology validation skipped."
            ),
        })

    return issues
