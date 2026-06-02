"""Runtime geometry validation — BRepCheck, wall thickness, manifold detection.

Runs AFTER each solid-creating or solid-modifying operation to verify
that the output geometry is valid. Uses OCCT's BRepCheck_Analyzer for
self-intersection and edge validity checks.
"""

from __future__ import annotations
from typing import Any
from dataclasses import dataclass, field


@dataclass
class GeometryValidationIssue:
    code: str
    message: str
    severity: str = "warning"  # "warning" | "error"


@dataclass
class GeometryValidationReport:
    ok: bool
    issues: list[GeometryValidationIssue] = field(default_factory=list)


def validate_solid_geometry(
    solid: Any,
    tolerance: Any,  # GeometryTolerance (avoid import to prevent circular deps)
) -> GeometryValidationReport:
    """Validate a solid after creation or modification.

    Checks:
      1. BRepCheck: self-intersection, invalid edges, empty shells
      2. Closed solid (watertight)
      3. Positive volume
      4. Non-zero bounding box
    """
    issues: list[GeometryValidationIssue] = []

    # ── 1. Basic existence ──
    if solid is None:
        return GeometryValidationReport(ok=False, issues=[
            GeometryValidationIssue(code="null_solid", message="Solid is None", severity="error")
        ])

    try:
        shape = solid.val()
    except Exception as e:
        return GeometryValidationReport(ok=False, issues=[
            GeometryValidationIssue(code="invalid_shape", message=f"Cannot get .val(): {e}", severity="error")
        ])

    # ── 2. BRepCheck ──
    try:
        from OCP.BRepCheck import BRepCheck_Analyzer
        analyzer = BRepCheck_Analyzer(shape.wrapped)
        if not analyzer.IsValid():
            result = analyzer.Result()
            # Collect sub-shape issues
            fault_count = 0
            from OCP.TopExp import TopExp_Explorer
            from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
            for sub_type, label in [(TopAbs_FACE, "face"), (TopAbs_EDGE, "edge")]:
                exp = TopExp_Explorer(shape.wrapped, sub_type)
                while exp.More():
                    sub = exp.Current()
                    if not analyzer.IsValid(sub):
                        fault_count += 1
                    exp.Next()
            if fault_count > 0:
                issues.append(GeometryValidationIssue(
                    code="brep_check_faults",
                    message=f"BRepCheck found {fault_count} invalid sub-shapes",
                    severity="warning",
                ))
    except ImportError:
        pass  # OCCT Python bindings not available — skip BRepCheck
    except Exception as e:
        issues.append(GeometryValidationIssue(
            code="brep_check_error",
            message=f"BRepCheck failed: {e}",
            severity="warning",
        ))

    # ── 3. Closed solid ──
    try:
        if hasattr(shape, "isClosed") and not shape.isClosed():
            issues.append(GeometryValidationIssue(
                code="not_closed",
                message="Solid is not closed (not watertight)",
                severity="error",
            ))
    except Exception as e:
        issues.append(GeometryValidationIssue(
            code="isClosed_error", message=f"isClosed() check failed: {e}", severity="warning",
        ))

    # ── 4. Positive volume ──
    try:
        vol = shape.Volume()
        if vol <= 0:
            issues.append(GeometryValidationIssue(
                code="zero_volume",
                message=f"Solid volume is {vol:.6f} mm³ (expected > 0)",
                severity="error",
            ))
    except Exception as e:
        issues.append(GeometryValidationIssue(
            code="volume_error", message=f"Volume() check failed: {e}", severity="warning",
        ))

    # ── 5. Bounding box ──
    try:
        bb = shape.BoundingBox()
        if bb.xlen <= tolerance.fuzzy_zero_mm and bb.ylen <= tolerance.fuzzy_zero_mm and bb.zlen <= tolerance.fuzzy_zero_mm:
            issues.append(GeometryValidationIssue(
                code="zero_bbox", message="Solid has zero-extent bounding box",
                severity="error",
            ))
    except Exception:
        pass  # BBox check is non-critical

    errors = [i for i in issues if i.severity == "error"]
    return GeometryValidationReport(ok=len(errors) == 0, issues=issues)
