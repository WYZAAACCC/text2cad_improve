"""Semantic postcheck — verify generated geometry matches design intent.

Runs after STEP build succeeds. Compares MeasuredGeometry against
DesignIntentMetrics and produces a SemanticPostcheckReport.

Reference: lm_skill_base19.md §3.4
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from seekflow_engineering_tools.generative_cad.runtime.design_intent import (
    DesignIntentMetrics,
    RangeMm,
)


class MeasuredGeometry(BaseModel):
    """Geometry measurements from the built STEP solid."""
    bbox_x_mm: float
    bbox_y_mm: float
    bbox_z_mm: float
    volume_mm3: float
    body_count: int | None = None
    solid_count: int | None = None


class SemanticIssue(BaseModel):
    """A single semantic violation."""
    severity: Literal["warning", "error"]
    code: str
    message: str
    expected: dict = Field(default_factory=dict)
    actual: dict = Field(default_factory=dict)


class SemanticPostcheckReport(BaseModel):
    """Result of semantic postcheck."""
    semantic_valid: bool
    measured: MeasuredGeometry | None = None
    issues: list[SemanticIssue] = Field(default_factory=list)

    @classmethod
    def ok(cls, measured: MeasuredGeometry) -> "SemanticPostcheckReport":
        return cls(semantic_valid=True, measured=measured, issues=[])

    @classmethod
    def fail(cls, measured: MeasuredGeometry | None, issues: list[SemanticIssue]) -> "SemanticPostcheckReport":
        return cls(semantic_valid=False, measured=measured, issues=issues)


def _in_range(value: float | None, r: "RangeMm | None", tolerance_pct: float = 0.05) -> bool:
    """Check if value falls within the range, expanded by tolerance_pct."""
    if value is None or r is None:
        return True
    margin = max(abs(r.max - r.min) * tolerance_pct, 0.5)
    return (r.min - margin) <= value <= (r.max + margin)


def run_semantic_postcheck(
    step_path: str | None = None,
    solid=None,
    *,
    design_intent: DesignIntentMetrics | None = None,
    degraded_ops: list[dict] | None = None,
) -> SemanticPostcheckReport:
    """Compare measured geometry against design intent.

    Args:
        step_path: Path to STEP file (optional, for measurement).
        solid: Pre-loaded CadQuery solid (optional, for measurement).
        design_intent: Extracted design intent metrics.
        degraded_ops: List of degraded operations from runtime.

    Returns:
        SemanticPostcheckReport with semantic_valid=True only if all
        applicable checks pass.
    """
    # ── Measure geometry ──
    measured = None
    if solid is not None:
        try:
            bb = solid.BoundingBox()
            vol = solid.Volume()
            measured = MeasuredGeometry(
                bbox_x_mm=round(bb.xlen, 3),
                bbox_y_mm=round(bb.ylen, 3),
                bbox_z_mm=round(bb.zlen, 3),
                volume_mm3=round(vol, 3),
            )
        except Exception:
            pass
    elif step_path is not None:
        try:
            import cadquery as cq
            result = cq.importers.importStep(str(step_path))
            s = result.val()
            bb = s.BoundingBox()
            vol = s.Volume()
            measured = MeasuredGeometry(
                bbox_x_mm=round(bb.xlen, 3),
                bbox_y_mm=round(bb.ylen, 3),
                bbox_z_mm=round(bb.zlen, 3),
                volume_mm3=round(vol, 3),
            )
        except Exception:
            pass

    # ── No design intent → pass with no checks ──
    if design_intent is None:
        return SemanticPostcheckReport(semantic_valid=True, measured=measured)

    issues: list[SemanticIssue] = []

    # ── Check degraded ops ──
    if not design_intent.allow_degraded_ops and degraded_ops:
        issues.append(SemanticIssue(
            severity="error",
            code="degraded_ops_not_allowed",
            message=f"{len(degraded_ops)} operation(s) degraded but allow_degraded_ops=False",
            expected={"degraded_ops": 0},
            actual={"degraded_ops": len(degraded_ops)},
        ))

    if measured is None:
        return SemanticPostcheckReport(
            semantic_valid=len(issues) == 0,
            measured=None,
            issues=issues,
        )

    # ── BBox checks ──
    if design_intent.bbox:
        bbox = design_intent.bbox
        checks = [
            ("bbox_x", measured.bbox_x_mm, bbox.x_mm),
            ("bbox_y", measured.bbox_y_mm, bbox.y_mm),
            ("bbox_z", measured.bbox_z_mm, bbox.z_mm),
        ]
        for dim_name, actual_val, expected_range in checks:
            if expected_range and not _in_range(actual_val, expected_range):
                issues.append(SemanticIssue(
                    severity="error",
                    code=f"bbox_{dim_name}_out_of_range",
                    message=(
                        f"BBox {dim_name}={actual_val:.1f}mm outside expected "
                        f"[{expected_range.min}-{expected_range.max}]mm"
                    ),
                    expected={"min": expected_range.min, "max": expected_range.max},
                    actual={dim_name: actual_val},
                ))

    # ── Volume checks ──
    if design_intent.volume:
        vol = design_intent.volume
        if vol.min_mm3 is not None and measured.volume_mm3 < vol.min_mm3 * 0.95:
            issues.append(SemanticIssue(
                severity="error",
                code="volume_too_small",
                message=(
                    f"Volume={measured.volume_mm3:.0f}mm3 below expected "
                    f"minimum {vol.min_mm3:.0f}mm3"
                ),
                expected={"min_mm3": vol.min_mm3},
                actual={"volume_mm3": measured.volume_mm3},
            ))
        if vol.max_mm3 is not None and measured.volume_mm3 > vol.max_mm3 * 1.05:
            issues.append(SemanticIssue(
                severity="error",
                code="volume_too_large",
                message=(
                    f"Volume={measured.volume_mm3:.0f}mm3 above expected "
                    f"maximum {vol.max_mm3:.0f}mm3"
                ),
                expected={"max_mm3": vol.max_mm3},
                actual={"volume_mm3": measured.volume_mm3},
            ))

    # ── Critical dimensions ──
    for cd in design_intent.critical_dimensions:
        dim_map = {
            "bbox_x": measured.bbox_x_mm,
            "bbox_y": measured.bbox_y_mm,
            "bbox_z": measured.bbox_z_mm,
            "volume_mm3": measured.volume_mm3,
            "outer_diameter_xy": max(measured.bbox_x_mm, measured.bbox_y_mm),
            "height_z": measured.bbox_z_mm,
        }
        actual_val = dim_map.get(cd.measurement)
        if actual_val is not None:
            if abs(actual_val - cd.target_mm) > cd.tolerance_mm:
                issues.append(SemanticIssue(
                    severity="error",
                    code=f"critical_dim_{cd.name}",
                    message=(
                        f"{cd.name}={actual_val:.1f}mm, expected "
                        f"{cd.target_mm}mm ±{cd.tolerance_mm}mm"
                    ),
                    expected={"target": cd.target_mm, "tolerance": cd.tolerance_mm},
                    actual={"value": actual_val},
                ))

    semantic_valid = not any(i.severity == "error" for i in issues)
    return SemanticPostcheckReport(
        semantic_valid=semantic_valid,
        measured=measured,
        issues=issues,
    )
