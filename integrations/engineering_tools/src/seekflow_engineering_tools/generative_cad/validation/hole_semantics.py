"""Hole semantic validator — enforces semantic correctness of hole placements.

Checks:
  1. Legacy cut_hole with axis=X/Y must provide 3D position (not ambiguous 2D)
  2. V2 holes must have target_face (not null/empty)
  3. Hole diameter must be positive and finite
  4. Required holes must not be silently degradable

Reference: llm_skill_base21.md §5.2, AUDIT P0-4 (fixed: uses ValidationIssue)
"""

from __future__ import annotations

import math

from seekflow_engineering_tools.generative_cad.validation.reports import (
    ValidationIssue,
    ValidationReport,
)


def validate_hole_semantics(subject) -> ValidationReport:
    """Validate hole operation semantics across the document.

    Applies to: RawGcadDocument or CanonicalGcadDocument.
    """
    issues: list[ValidationIssue] = []
    stage = "geometry_preflight"

    nodes = subject.get("nodes", []) if isinstance(subject, dict) else getattr(subject, "nodes", [])

    for n in nodes:
        # Unify dict / model access
        if isinstance(n, dict):
            op = n.get("op", "")
            nid = n.get("id", "")
            params = n.get("params", {})
            required = n.get("required", True)
        else:
            op = n.op
            nid = n.id
            params = n.params
            required = n.required

        # ── LEGACY cut_hole ──
        if op == "cut_hole":
            axis = params.get("axis", "Z")
            pos = params.get("position_mm", [])
            dia = params.get("diameter_mm", 0)

            # Side hole (axis=X/Y) with 2D position is ambiguous
            if axis in ("X", "Y") and len(pos) < 3:
                issues.append(ValidationIssue(
                    stage=stage,
                    code="LEGACY_SIDE_HOLE_REQUIRES_3D_POSITION",
                    message=(
                        f"Legacy cut_hole node '{nid}' uses axis={axis!r} with "
                        f"{len(pos)}D position_mm. The Z coordinate is ambiguous "
                        f"and will default to the bounding-box midplane. "
                        f"Use cut_hole_v2 with target_face + center_uv_mm for explicit semantics."
                    ),
                    severity="warning",  # warning, not error — old cases still work
                    node_id=nid,
                ))

            if not _is_finite_positive(dia):
                issues.append(ValidationIssue(
                    stage=stage,
                    code="HOLE_DIAMETER_INVALID",
                    message=f"cut_hole node '{nid}' has invalid diameter_mm={dia}",
                    severity="error",
                    node_id=nid,
                ))

            if required and not params:
                issues.append(ValidationIssue(
                    stage=stage,
                    code="REQUIRED_HOLE_EMPTY_PARAMS",
                    message=f"Required cut_hole node '{nid}' has empty params",
                    severity="error",
                    node_id=nid,
                ))

        # ── LEGACY cut_hole_pattern_linear ──
        elif op == "cut_hole_pattern_linear":
            axis = params.get("axis", "Z")
            if axis in ("X", "Y"):
                issues.append(ValidationIssue(
                    stage=stage,
                    code="LEGACY_PATTERN_SIDE_HOLE_DEGRADED",
                    message=(
                        f"Legacy cut_hole_pattern_linear node '{nid}' uses axis={axis!r} "
                        f"but the handler currently only supports Z-axis (XY plane). "
                        f"Use cut_hole_pattern_linear_v2 for side-face patterns."
                    ),
                    severity="warning",
                    node_id=nid,
                ))

        # ── V2 cut_hole_v2 ──
        elif op == "cut_hole_v2":
            placement = params.get("placement")
            if not placement:
                issues.append(ValidationIssue(
                    stage=stage,
                    code="MISSING_HOLE_PLACEMENT",
                    message=f"cut_hole_v2 node '{nid}' missing required 'placement' field",
                    severity="error",
                    node_id=nid,
                ))
            elif isinstance(placement, dict):
                target_face = placement.get("target_face", "")
                if not target_face:
                    issues.append(ValidationIssue(
                        stage=stage,
                        code="MISSING_TARGET_FACE",
                        message=f"cut_hole_v2 node '{nid}' placement missing target_face",
                        severity="error",
                        node_id=nid,
                    ))
                normal = placement.get("normal_axis", "")
                if not normal:
                    issues.append(ValidationIssue(
                        stage=stage,
                        code="MISSING_NORMAL_AXIS",
                        message=f"cut_hole_v2 node '{nid}' placement missing normal_axis",
                        severity="error",
                        node_id=nid,
                    ))

        # ── V2 hole_pattern_linear_v2 ──
        elif op == "cut_hole_pattern_linear_v2":
            placement = params.get("placement")
            if not placement:
                issues.append(ValidationIssue(
                    stage=stage,
                    code="MISSING_HOLE_PATTERN_PLACEMENT",
                    message=f"cut_hole_pattern_linear_v2 node '{nid}' missing 'placement'",
                    severity="error",
                    node_id=nid,
                ))

        # ── drill_hole_3d ──
        elif op == "drill_hole_3d":
            direction = params.get("direction", (0, 0, 0))
            if isinstance(direction, (list, tuple)):
                mag = sum(v * v for v in direction)
                if mag < 1e-9:
                    issues.append(ValidationIssue(
                        stage=stage,
                        code="ZERO_DIRECTION_VECTOR",
                        message=f"drill_hole_3d node '{nid}' has zero direction vector",
                        severity="error",
                        node_id=nid,
                    ))

        # ── cut_circular_hole_pattern (axisymmetric) ──
        elif op == "cut_circular_hole_pattern":
            count = params.get("count", 0)
            hole_dia = params.get("hole_dia_mm", 0)
            pcd = params.get("pcd_mm", 0)
            if count < 2:
                issues.append(ValidationIssue(
                    stage=stage,
                    code="CIRCULAR_PATTERN_COUNT_TOO_LOW",
                    message=f"cut_circular_hole_pattern node '{nid}' count={count} must be >= 2",
                    severity="error",
                    node_id=nid,
                ))
            if not _is_finite_positive(hole_dia):
                issues.append(ValidationIssue(
                    stage=stage,
                    code="CIRCULAR_PATTERN_HOLE_DIA_INVALID",
                    message=f"cut_circular_hole_pattern node '{nid}' hole_dia_mm={hole_dia} invalid",
                    severity="error",
                    node_id=nid,
                ))
            if not _is_finite_positive(pcd):
                issues.append(ValidationIssue(
                    stage=stage,
                    code="CIRCULAR_PATTERN_PCD_INVALID",
                    message=f"cut_circular_hole_pattern node '{nid}' pcd_mm={pcd} invalid",
                    severity="error",
                    node_id=nid,
                ))

    return ValidationReport(
        ok=not any(i.severity == "error" for i in issues),
        stage=stage,
        issues=issues,
    )


def _is_finite_positive(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v) and v > 0
