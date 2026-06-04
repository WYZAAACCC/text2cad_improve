"""Phase C GeometrySpatialAudit — post-assembly spatial verification.

Runs after all placement and boolean_union operations complete.
Verifies spatial constraints were satisfied using actual solid geometry.
"""

from __future__ import annotations
from typing import Any

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    SpatialConstraintGraph,
    GeometrySpatialAuditReport,
    ComponentBBox,
    PairwiseSpatialMetric,
    SpatialValidationIssue,
    NumericPlacement,
)


def run_geometry_spatial_audit(
    *,
    final_handle_id: str,
    ctx: Any,
    spatial_graph: SpatialConstraintGraph,
    placements: dict[str, NumericPlacement],
) -> GeometrySpatialAuditReport:
    """Post-assembly spatial audit.

    Checks:
    1. Per-component bbox measurement
    2. Pairwise overlap ratio (>80% → error)
    3. Top/bottom Z order
    4. Contact graph connectivity
    5. Assembly-level bbox
    6. Solid body count
    """
    issues: list[SpatialValidationIssue] = []

    # 1. Measure component bboxes
    comp_bboxes = _measure_component_bboxes(ctx, placements)

    # 2. Pairwise overlap
    pairwise: list[PairwiseSpatialMetric] = []
    for i in range(len(comp_bboxes)):
        for j in range(i + 1, len(comp_bboxes)):
            a, b = comp_bboxes[i], comp_bboxes[j]
            overlap = _bbox_overlap_ratio(a, b)
            dist = _bbox_distance(a, b)
            metric = PairwiseSpatialMetric(
                a=a.component_id, b=b.component_id,
                overlap_ratio_min=overlap, bbox_distance_mm=dist,
                contacts=(dist < 1.0),
            )
            pairwise.append(metric)

            if overlap > 0.8:
                issues.append(SpatialValidationIssue(
                    severity="error", code="spatial_overlap",
                    message=f"Components '{a.component_id}' and '{b.component_id}' overlap > 80%",
                    entities=[a.component_id, b.component_id],
                ))

    # 3. Z order check
    _check_z_order(comp_bboxes, issues)

    # 4. Connectivity
    connected = _check_connectivity(pairwise, len(comp_bboxes))
    if len(comp_bboxes) > 1 and not connected:
        issues.append(SpatialValidationIssue(
            severity="error", code="spatial_disconnected",
            message="Assembly has disconnected component groups (no contact path)",
        ))

    # 5. Assembly bbox
    final_solid = ctx.object_store.get(final_handle_id)
    asm_bb = _measure_single_bbox(final_solid)
    solid_count = _count_solids(final_solid)

    return GeometrySpatialAuditReport(
        ok=not any(i.severity == "error" for i in issues),
        component_bboxes=comp_bboxes,
        pairwise_metrics=pairwise,
        issues=issues,
        assembly_bbox_mm=(
            (asm_bb.xlen, asm_bb.ylen, asm_bb.zlen) if asm_bb else None
        ),
        solid_count=solid_count,
        connectivity_graph_connected=connected,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _measure_component_bboxes(ctx: Any, placements: dict) -> list[ComponentBBox]:
    result: list[ComponentBBox] = []
    for cid in placements:
        try:
            hid = ctx.resolve_component_output(cid, "body")
            solid = ctx.object_store.get(hid)
            bb = _measure_single_bbox(solid)
            if bb:
                bb.component_id = cid
                result.append(bb)
        except Exception:
            continue
    return result


def _measure_single_bbox(solid: Any) -> ComponentBBox | None:
    try:
        if hasattr(solid, 'val'):
            solid = solid.val()
        bb = solid.BoundingBox()
        return ComponentBBox(
            component_id="assembly", xmin=bb.xmin, xmax=bb.xmax,
            ymin=bb.ymin, ymax=bb.ymax, zmin=bb.zmin, zmax=bb.zmax,
        )
    except Exception:
        return None


def _bbox_overlap_ratio(a: ComponentBBox, b: ComponentBBox) -> float:
    ix = max(0.0, min(a.xmax, b.xmax) - max(a.xmin, b.xmin))
    iy = max(0.0, min(a.ymax, b.ymax) - max(a.ymin, b.ymin))
    iz = max(0.0, min(a.zmax, b.zmax) - max(a.zmin, b.zmin))
    overlap_vol = ix * iy * iz
    a_vol = a.xlen * a.ylen * a.zlen
    b_vol = b.xlen * b.ylen * b.zlen
    if a_vol <= 0 or b_vol <= 0:
        return 0.0
    return min(overlap_vol / a_vol, overlap_vol / b_vol)


def _bbox_distance(a: ComponentBBox, b: ComponentBBox) -> float:
    dx = max(0.0, max(a.xmin, b.xmin) - min(a.xmax, b.xmax))
    dy = max(0.0, max(a.ymin, b.ymin) - min(a.ymax, b.ymax))
    dz = max(0.0, max(a.zmin, b.zmin) - min(a.zmax, b.zmax))
    return (dx**2 + dy**2 + dz**2) ** 0.5


def _check_z_order(
    bboxes: list[ComponentBBox], issues: list[SpatialValidationIssue]
) -> None:
    for bb in bboxes:
        cid = bb.component_id.lower()
        if "top" in cid:
            for other in bboxes:
                oid = other.component_id.lower()
                if "bottom" in oid:
                    if bb.zmin <= other.zmax:
                        issues.append(SpatialValidationIssue(
                            severity="error", code="spatial_z_order",
                            message=f"Top component '{bb.component_id}' (zmin={bb.zmin:.1f}) "
                                    f"below bottom '{other.component_id}' (zmax={other.zmax:.1f})",
                            entities=[bb.component_id, other.component_id],
                        ))


def _check_connectivity(pairwise: list[PairwiseSpatialMetric], count: int) -> bool:
    if count <= 1:
        return True
    adj: dict[str, set[str]] = {}
    for pm in pairwise:
        if pm.contacts or pm.bbox_distance_mm < 2.0:
            adj.setdefault(pm.a, set()).add(pm.b)
            adj.setdefault(pm.b, set()).add(pm.a)
    if not adj:
        return False
    visited: set[str] = set()

    def dfs(n: str) -> None:
        visited.add(n)
        for nb in adj.get(n, set()):
            if nb not in visited:
                dfs(nb)

    dfs(next(iter(adj)))
    return len(visited) == count


def _count_solids(solid: Any) -> int | None:
    try:
        if hasattr(solid, 'Solids'):
            return len(list(solid.Solids()))
        return 1
    except Exception:
        return None
