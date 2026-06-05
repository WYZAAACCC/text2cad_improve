"""GeometryHealth — per-operation runtime geometry health assessment.

Provides best-effort health checks on solid bodies using the existing
GeometryRuntime inspection methods. Results are recorded in RuntimeContext
and exposed in metadata for diagnostic and repair tooling.

Phase 2: health recording + required degradation enforcement.
Phase 3+: health score aggregation and trend analysis.

Design: OCP/CadQuery unavailable → health.status = "unknown" (not error).
Only explicitly detected geometric defects cause "error" status.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GeometryHealth(BaseModel):
    """Health assessment of a single solid body after an operation.

    Captured after each creates_solid/modifies_solid operation.
    Accumulated in RuntimeContext.geometry_health_log for diagnostics.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "warning", "error", "unknown"] = Field(
        default="unknown",
        description=(
            "Overall health status: "
            "ok = valid closed single solid; "
            "warning = minor issues (multi-body, small volume); "
            "error = invalid/missing geometry; "
            "unknown = could not assess (OCP unavailable)."
        ),
    )

    valid_brep: bool | None = Field(default=None, description="BRepCheck passed.")
    closed: bool | None = Field(default=None, description="Solid is closed.")
    body_count: int | None = Field(default=None, description="Number of solid bodies.")
    bbox_mm: list[float] | None = Field(default=None, description="[xlen, ylen, zlen] in mm.")
    volume_mm3: float | None = Field(default=None, description="Volume in mm³.")

    small_edges_count: int | None = Field(default=None)
    small_faces_count: int | None = Field(default=None)

    score: float | None = Field(
        default=None,
        description=(
            "Normalized health score 0.0–1.0: "
            "1.0 = perfect; 0.85 = bbox missing; 0.8 = multi-body; "
            "0.5 = not closed; None = unknown."
        ),
    )
    issues: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of health issues found.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Health inspection (best-effort, uses GeometryRuntime)
# ═══════════════════════════════════════════════════════════════════════════════


def inspect_geometry_health(
    solid_obj: Any,
    geometry_runtime,
    tolerance: Any,
    *,
    expected_body_count: int = 1,
) -> GeometryHealth:
    """Inspect a solid object and return a GeometryHealth assessment.

    Best-effort: if any inspection method fails or is unavailable,
    the corresponding field remains None and status degrades gracefully.
    Only explicit geometric defects raise status to "error".

    Args:
        solid_obj: A CadQuery Workplane/Solid or OCP TopoDS_Shape.
        geometry_runtime: A GeometryRuntime instance (e.g. CadQueryRuntime).
        tolerance: GeometryTolerance for the current run.
        expected_body_count: Expected number of solid bodies (default 1).

    Returns:
        GeometryHealth with best-effort assessment.
    """
    issues: list[dict[str, Any]] = []
    valid_brep: bool | None = None
    closed: bool | None = None
    body_count: int | None = None
    bbox_mm: list[float] | None = None
    volume_mm3: float | None = None

    # ── 1. Body count ──
    try:
        body_count = geometry_runtime.count_bodies(solid_obj)
    except Exception:
        pass

    # ── 2. Closed solid check ──
    try:
        closed_result = geometry_runtime.validate_closed_solid(solid_obj)
        if isinstance(closed_result, dict):
            closed = closed_result.get("ok", None)
            if closed is False:
                issues.append({
                    "code": "not_closed",
                    "message": closed_result.get("issue", "Solid is not closed"),
                    "severity": "error",
                })
    except Exception:
        pass

    # ── 3. BBox ──
    try:
        bbox_mm = geometry_runtime.compute_bbox_mm(solid_obj)
    except Exception:
        pass

    # ── 4. Volume ──
    try:
        if hasattr(solid_obj, "Volume"):
            volume_mm3 = solid_obj.Volume()
        elif hasattr(solid_obj, "val") and hasattr(solid_obj.val(), "Volume"):
            volume_mm3 = solid_obj.val().Volume()
    except Exception:
        pass

    # ── 5. BRepCheck (valid_brep) ──
    try:
        from seekflow_engineering_tools.generative_cad.validation.geometry_validate import (
            validate_solid_geometry,
        )
        geo_report = validate_solid_geometry(solid_obj, tolerance)
        valid_brep = geo_report.ok
        for issue in geo_report.issues:
            issues.append({
                "code": issue.code,
                "message": issue.message,
                "severity": issue.severity,
            })
    except Exception:
        pass

    # ── Compute status and score ──
    status, score = _compute_health_status(
        valid_brep=valid_brep,
        closed=closed,
        body_count=body_count,
        bbox_mm=bbox_mm,
        volume_mm3=volume_mm3,
        expected_body_count=expected_body_count,
        issues=issues,
    )

    return GeometryHealth(
        status=status,
        valid_brep=valid_brep,
        closed=closed,
        body_count=body_count,
        bbox_mm=bbox_mm,
        volume_mm3=volume_mm3,
        score=score,
        issues=issues,
    )


def _compute_health_status(
    *,
    valid_brep: bool | None,
    closed: bool | None,
    body_count: int | None,
    bbox_mm: list[float] | None,
    volume_mm3: float | None,
    expected_body_count: int,
    issues: list[dict[str, Any]],
) -> tuple[Literal["ok", "warning", "error", "unknown"], float | None]:
    """Determine health status and normalized score from inspection results."""

    # All checks unavailable → unknown
    if all(v is None for v in (valid_brep, closed, body_count, bbox_mm, volume_mm3)):
        return "unknown", None

    # Explicitly not closed → error
    if closed is False:
        return "error", 0.5

    # Explicitly not valid BRep → error
    if valid_brep is False:
        return "error", 0.5

    # Volume <= 0 → error
    if volume_mm3 is not None and volume_mm3 <= 0:
        return "error", 0.5

    # BBox degenerate → error
    if bbox_mm is not None and any(d <= 0 for d in bbox_mm):
        return "error", 0.5

    # Has error-severity issues from BRepCheck → error
    if any(i.get("severity") == "error" for i in issues):
        return "error", 0.6

    # Multi-body → warning
    if body_count is not None and body_count != expected_body_count:
        return "warning", 0.8

    # BBox missing but otherwise ok → warning
    if bbox_mm is None:
        return "warning", 0.85

    # Volume near zero → warning
    if volume_mm3 is not None and 0 < volume_mm3 < 0.001:
        return "warning", 0.9

    # Has warning-severity issues → warning
    if any(i.get("severity") == "warning" for i in issues):
        return "warning", 0.9

    # All checks passed → ok
    return "ok", 1.0
