"""Geometry preflight — lightweight geometric reasoning before CadQuery execution.

Runs before the kernel to catch LLM-hallucinated dimensions early.
"""

from __future__ import annotations

from typing import Any

DEFAULT_GEOMETRY_POLICY = {
    "min_edge_length_mm": 0.25,
    "min_wall_thickness_mm": 1.0,
    "min_boolean_clearance_mm": 0.2,
    "min_hole_to_boundary_margin_mm": 1.0,
    "max_fillet_ratio_to_local_thickness": 0.25,
    "max_nodes": 64,
    "max_boolean_ops": 256,
    "max_profile_points": 128,
}


def run_geometry_preflight(
    spec,  # GenerativeCADSpec
) -> dict:
    """Run geometry preflight for all nodes in a GenerativeCADSpec.

    Returns {"ok": bool, "stage": "geometry_preflight", "issues": [...]}.
    """
    from seekflow_engineering_tools.generative_cad.legacy.registry_v01 import BASE_REGISTRY

    issues: list[dict] = []

    if len(spec.feature_graph.nodes) > DEFAULT_GEOMETRY_POLICY["max_nodes"]:
        issues.append({
            "code": "too_many_nodes",
            "message": (
                f"Feature graph has {len(spec.feature_graph.nodes)} nodes, "
                f"max {DEFAULT_GEOMETRY_POLICY['max_nodes']}."
            ),
            "severity": "error",
            "stage": "geometry_preflight",
        })
        return {"ok": False, "stage": "geometry_preflight", "issues": issues}

    nodes_raw = [n.model_dump() for n in spec.feature_graph.nodes]

    for node in spec.feature_graph.nodes:
        base = BASE_REGISTRY.get(node.base_id)
        if base is None:
            continue  # Caught earlier by graph validation

        preflight_fn = None
        if hasattr(base, "_preflight_handlers"):
            preflight_fn = base._preflight_handlers.get(node.op)  # type: ignore[union-attr]

        if preflight_fn is not None:
            try:
                node_issues = preflight_fn(node.model_dump(), nodes_raw)
                for issue in node_issues:
                    issue.setdefault("stage", "geometry_preflight")
                issues.extend(node_issues)
            except Exception as exc:
                issues.append({
                    "code": "preflight_handler_error",
                    "message": f"Preflight handler for {node.op!r} failed: {exc}",
                    "node_id": node.id,
                    "severity": "error",
                    "stage": "geometry_preflight",
                })

    errors = [i for i in issues if i.get("severity") == "error"]
    return {
        "ok": len(errors) == 0,
        "stage": "geometry_preflight",
        "issues": issues,
    }
