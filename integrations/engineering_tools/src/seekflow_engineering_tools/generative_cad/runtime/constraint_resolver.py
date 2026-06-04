"""Phase C ConstraintResolver — symbolic constraints → numeric placements.

Runs AFTER all leaf components execute and BEFORE assembly composition.
Substitutes actual bbox measurements into symbolic constraints to compute
concrete translation/rotation coordinates.

Key rules:
  S001: Default global frame X=left-right, Y=front-back, Z=bottom-top
  S010: Z-axis stack: lower.zmax + offset = upper.zmin
  S020: Between axial chain: topological sort along Z
  S030: Symmetric pair: A.x = -d/2, B.x = +d/2
  S040: Coaxial: align X,Y centers for Z-axis coaxial
  S080: Identity placement ban for multi-component
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    SpatialConstraintGraph,
    PlacementConstraint,
    NumericPlacement,
    ComponentBBox,
    Confidence,
)


@dataclass
class ResolverCtx:
    """Solver context holding all state during resolution."""
    component_bboxes: dict[str, ComponentBBox] = field(default_factory=dict)
    placements: dict[str, NumericPlacement] = field(default_factory=dict)
    graph: SpatialConstraintGraph | None = None
    default_spacing_mm: float = 30.0
    issues: list[str] = field(default_factory=list)


def resolve_placements(
    constraint_graph: SpatialConstraintGraph,
    bboxes: dict[str, ComponentBBox],
    default_spacing_mm: float = 30.0,
) -> tuple[dict[str, NumericPlacement], list[str]]:
    """Convert symbolic constraints + actual bboxes → numeric placements.

    Resolution order:
    1. identity → (0,0,0)
    2. stack → Z-axis stacking (topological sort)
    3. align_axis → coaxial XY alignment
    4. symmetric → X-axis mirror

    Returns (placements, issues).
    """
    ctx = ResolverCtx(
        component_bboxes=bboxes,
        graph=constraint_graph,
        default_spacing_mm=default_spacing_mm,
    )

    # Initialize all placements as identity (to be overridden)
    for cid in bboxes:
        ctx.placements[cid] = NumericPlacement(
            component_id=cid,
            translation_mm=(0.0, 0.0, 0.0),
            source="solver_derived",
            is_pending=True,
            pending_reason="not yet solved",
        )

    _resolve_identity(ctx)
    _resolve_stack(ctx)
    _resolve_align_axis(ctx)
    _resolve_symmetric(ctx)
    _resolve_contact(ctx)

    # Mark remaining as default identity
    for p in ctx.placements.values():
        if p.is_pending and p.pending_reason == "not yet solved":
            p.is_pending = False
            p.pending_reason = "default identity (no constraint applied)"

    return ctx.placements, ctx.issues


# ═══════════════════════════════════════════════════════════════════════════════
# Solver rules
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_identity(ctx: ResolverCtx) -> None:
    """S001: Explicit identity placement → (0,0,0)."""
    if ctx.graph is None:
        return
    for c in ctx.graph.constraints:
        if c.type == "identity" and len(c.entities) >= 1:
            cid = c.entities[0]
            if cid in ctx.placements:
                ctx.placements[cid] = NumericPlacement(
                    component_id=cid,
                    translation_mm=(0.0, 0.0, 0.0),
                    source="solver_derived",
                    is_pending=False,
                    confidence=Confidence(value=1.0, reason="explicit identity constraint"),
                )


def _resolve_stack(ctx: ResolverCtx) -> None:
    """S010/S020: Z-axis stacking via Kahn topological sort.

    Constraint: lower.zmax + offset = upper.zmin
    Algorithm:
    1. Build DAG from stack constraints
    2. Kahn topological sort
    3. zmin = max(all lower_neighbor.zmax + offset)
    """
    if ctx.graph is None:
        return

    stack_cs = [
        c for c in ctx.graph.constraints
        if c.type == "stack" and c.axis == "Z" and len(c.entities) >= 2
    ]
    if not stack_cs:
        return

    # Build adjacency: lower → [(upper, offset)]
    above: dict[str, list[tuple[str, float]]] = {}
    in_deg: dict[str, int] = {}
    all_ids: set[str] = set()

    for c in stack_cs:
        lower, upper = c.entities[0], c.entities[1]
        above.setdefault(lower, []).append((upper, c.offset_mm))
        in_deg[upper] = in_deg.get(upper, 0) + 1
        in_deg.setdefault(lower, 0)
        all_ids.add(lower)
        all_ids.add(upper)

    # Kahn topological sort
    queue = [cid for cid in all_ids if in_deg.get(cid, 0) == 0]
    order: list[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for upper, _ in above.get(node, []):
            in_deg[upper] -= 1
            if in_deg[upper] == 0:
                queue.append(upper)

    if len(order) != len(all_ids):
        ctx.issues.append("stack constraint cycle detected, using partial order")
        order = list(all_ids)

    # Build reverse lookup: for each upper, find its lower neighbors
    lower_of: dict[str, list[tuple[str, float]]] = {}
    for lower, edges in above.items():
        for upper, offset in edges:
            lower_of.setdefault(upper, []).append((lower, offset))

    # Compute zmin for each component in topological order
    for cid in order:
        bbox = ctx.component_bboxes.get(cid)
        if bbox is None:
            continue

        zmin_candidates = [0.0]
        for lower_cid, offset in lower_of.get(cid, []):
            lower_bbox = ctx.component_bboxes.get(lower_cid)
            if lower_bbox is None:
                continue
            lower_pl = ctx.placements.get(lower_cid)
            lower_z = lower_pl.translation_mm[2] if lower_pl else 0.0
            zmin_candidates.append(lower_z + lower_bbox.zlen + offset)

        new_zmin = max(zmin_candidates)
        current = ctx.placements.get(cid)
        if current:
            ctx.placements[cid] = NumericPlacement(
                component_id=cid,
                translation_mm=(
                    current.translation_mm[0],
                    current.translation_mm[1],
                    new_zmin,
                ),
                rotation_deg_xyz=current.rotation_deg_xyz,
                source="solver_derived",
                confidence=Confidence(value=1.0, reason="solved from stack constraints"),
                is_pending=False,
            )


def _resolve_contact(ctx: ResolverCtx) -> None:
    """Verify contact constraints (does not modify placement).

    Contact constraints require bbox distance <= tolerance at audit time.
    Phase C only checks that both entities have bbox data available.
    Actual distance verification happens in GeometrySpatialAudit (Phase C post-assembly).
    """
    if ctx.graph is None:
        return
    for c in ctx.graph.constraints:
        if c.type != "contact":
            continue
        for eid in c.entities:
            if eid not in ctx.component_bboxes:
                ctx.issues.append(
                    f"contact constraint '{c.constraint_id}': "
                    f"no bbox data for entity '{eid}'"
                )


def _resolve_align_axis(ctx: ResolverCtx) -> None:
    """S040: Coaxial alignment. Align XY centers (for Z-axis coaxial)."""
    if ctx.graph is None:
        return

    for c in ctx.graph.constraints:
        if c.type != "align_axis" or len(c.entities) < 2:
            continue

        ref_id = c.entities[0]
        ref_bbox = ctx.component_bboxes.get(ref_id)
        ref_pl = ctx.placements.get(ref_id)
        if ref_bbox is None or ref_pl is None or ref_pl.is_pending:
            continue

        ref_center = (
            ref_pl.translation_mm[0] + ref_bbox.xlen / 2,
            ref_pl.translation_mm[1] + ref_bbox.ylen / 2,
            ref_pl.translation_mm[2] + ref_bbox.zlen / 2,
        )
        axis = c.axis or "Z"

        for target_id in c.entities[1:]:
            t_bbox = ctx.component_bboxes.get(target_id)
            t_pl = ctx.placements.get(target_id)
            if t_bbox is None or t_pl is None:
                continue

            if axis == "Z":
                new_x = ref_center[0] - t_bbox.xlen / 2
                new_y = ref_center[1] - t_bbox.ylen / 2
                ctx.placements[target_id] = NumericPlacement(
                    component_id=target_id,
                    translation_mm=(new_x, new_y, t_pl.translation_mm[2]),
                    rotation_deg_xyz=t_pl.rotation_deg_xyz,
                    source="solver_derived",
                    confidence=Confidence(value=1.0, reason="solved from coaxial constraint"),
                    is_pending=False,
                )


def _resolve_symmetric(ctx: ResolverCtx) -> None:
    """S030: Symmetric pair about YZ plane (X-axis mirror)."""
    if ctx.graph is None:
        return

    for c in ctx.graph.constraints:
        if c.type != "symmetric" or len(c.entities) < 2:
            continue

        a_id, b_id = c.entities[0], c.entities[1]
        a_bb = ctx.component_bboxes.get(a_id)
        b_bb = ctx.component_bboxes.get(b_id)
        if a_bb is None or b_bb is None:
            continue

        # Determine spacing
        if c.spacing_mm is not None:
            d = c.spacing_mm
        else:
            d = max(a_bb.xlen, b_bb.xlen) * 3.0
            ctx.issues.append(
                f"[assumption] symmetric_pair({a_id}, {b_id}): "
                f"no spacing specified, derived = {d:.1f}mm"
            )

        half_d = d / 2.0
        a_pl = ctx.placements.get(a_id, NumericPlacement(component_id=a_id))
        b_pl = ctx.placements.get(b_id, NumericPlacement(component_id=b_id))

        # Use the non-pending placement's Y/Z as the shared reference
        ref_y = a_pl.translation_mm[1] if not a_pl.is_pending else b_pl.translation_mm[1]
        ref_z = a_pl.translation_mm[2] if not a_pl.is_pending else b_pl.translation_mm[2]
        # If both are pending, use max of their Z (whichever was set by stack)
        if a_pl.is_pending and b_pl.is_pending:
            ref_z = max(a_pl.translation_mm[2], b_pl.translation_mm[2])
            ref_y = max(a_pl.translation_mm[1], b_pl.translation_mm[1])

        ctx.placements[a_id] = NumericPlacement(
            component_id=a_id,
            translation_mm=(
                -half_d - a_bb.xlen / 2,
                ref_y,
                ref_z,
            ),
            source="solver_derived",
            confidence=Confidence(value=0.85, reason="solved from symmetric_pair constraint"),
            is_pending=False,
            assumptions=[f"derived symmetric spacing={d:.1f}mm"] if c.spacing_mm is None else [],
        )
        ctx.placements[b_id] = NumericPlacement(
            component_id=b_id,
            translation_mm=(
                half_d - b_bb.xlen / 2,
                ref_y,
                ref_z,
            ),
            source="solver_derived",
            confidence=Confidence(value=0.85, reason="solved from symmetric_pair constraint"),
            is_pending=False,
            assumptions=[f"derived symmetric spacing={d:.1f}mm"] if c.spacing_mm is None else [],
        )
