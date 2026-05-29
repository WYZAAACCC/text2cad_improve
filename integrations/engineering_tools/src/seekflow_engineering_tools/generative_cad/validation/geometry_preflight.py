"""Geometry preflight validation — lightweight geometric sanity checks before runtime.

v0.3: runs at canonical level, calls dialect.preflight_component on each component.
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationIssue, ValidationReport

DEFAULT_GEOMETRY_POLICY = {
    "max_nodes": 64,
    "max_boolean_ops": 256,
    "max_profile_points": 128,
    "min_edge_length_mm": 0.25,
    "min_wall_thickness_mm": 1.0,
    "min_boolean_clearance_mm": 0.2,
    "min_hole_to_boundary_margin_mm": 1.0,
    "max_pattern_instances": 360,
    "max_fillet_ratio_to_local_thickness": 0.25,
}


def validate_geometry_preflight(canonical: CanonicalGcadDocument) -> ValidationReport:
    """Run geometry preflight: global checks + per-dialect preflight_component.

    Global checks:
    - max_nodes
    - max_boolean_ops
    - max_profile_points
    """
    stage = "geometry_preflight"
    issues: list[ValidationIssue] = []

    # ── Global checks ──
    if len(canonical.nodes) > DEFAULT_GEOMETRY_POLICY["max_nodes"]:
        issues.append(ValidationIssue(
            stage=stage, code="too_many_nodes",
            message=f"Graph has {len(canonical.nodes)} nodes, max {DEFAULT_GEOMETRY_POLICY['max_nodes']}",
            severity="error",
        ))
        return ValidationReport(ok=False, stage=stage, issues=issues)

    boolean_ops = [n for n in canonical.nodes if n.op in ("boolean_union", "boolean_cut", "boolean_intersect")]
    if len(boolean_ops) > DEFAULT_GEOMETRY_POLICY["max_boolean_ops"]:
        issues.append(ValidationIssue(
            stage=stage, code="too_many_boolean_ops",
            message=f"Graph has {len(boolean_ops)} boolean ops, max {DEFAULT_GEOMETRY_POLICY['max_boolean_ops']}",
            severity="error",
        ))

    # Check profile points for ops with profile_stations / points / sections
    for n in canonical.nodes:
        for key in ("profile_stations", "points", "sections"):
            val = n.typed_params.get(key) if n.typed_params else n.params.get(key)
            if isinstance(val, list) and len(val) > DEFAULT_GEOMETRY_POLICY["max_profile_points"]:
                issues.append(ValidationIssue(
                    stage=stage, code="too_many_profile_points",
                    message=f"Node {n.id!r} has {len(val)} {key}, max {DEFAULT_GEOMETRY_POLICY['max_profile_points']}",
                    severity="error", node_id=n.id, component_id=n.component,
                ))

    # ── Per-dialect preflight ──
    for component in canonical.components:
        try:
            dialect = require_dialect(component.owner_dialect)
        except KeyError:
            continue  # caught earlier

        nodes = [n for n in canonical.nodes if n.component == component.id]

        try:
            report = dialect.preflight_component(component, nodes)
        except Exception as exc:
            issues.append(ValidationIssue(
                stage=stage, code="preflight_handler_error",
                message=f"Dialect {component.owner_dialect!r} preflight error: {exc}",
                severity="error", component_id=component.id,
            ))
            continue

        issues.extend(report.issues)

    return ValidationReport(
        ok=not any(i.severity == "error" for i in issues),
        stage=stage,
        issues=issues,
    )
