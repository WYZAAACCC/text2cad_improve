"""Geometry preflight validation — lightweight geometric sanity checks before runtime.

v0.3: runs at canonical level, calls dialect.preflight_component on each component.
v0.8: 阈值迁移至 validation_kernel/policy.py (统一 Policy, 指导书 §16);
      本模块的 DEFAULT_GEOMETRY_POLICY 保留为兼容视图, 值由 policy 生成。
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationIssue, ValidationReport
from seekflow_engineering_tools.generative_cad.validation_kernel.policy import (
    default_validation_policy,
)

# 兼容视图 — 权威定义: validation_kernel.policy.GeometryPolicy (默认值与迁移前一致)
DEFAULT_GEOMETRY_POLICY = default_validation_policy().geometry.model_dump()


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
