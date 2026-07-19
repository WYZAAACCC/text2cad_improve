"""Composition dialect handlers — transform, pattern, boolean.

v1.0: hardened with input validation, degradation chains, and safe defaults.
All handlers follow the same pattern: validate → try full op → try fallback → warn+skip.
"""

from __future__ import annotations

import math

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
from seekflow_engineering_tools.generative_cad.runtime.resolve import (
    resolve_input_object,
)


def _store_solid(node: CanonicalNode, ctx: RuntimeContext, obj) -> str:
    if obj is None:
        raise RuntimeError(
            f"BUG: _store_solid called with None on '{node.id}'. "
            f"This should never happen — handler must guard against None."
        )
    solid_id = f"solid:{node.component}:{node.id}:body"
    handle = SolidHandle(id=solid_id, component_id=node.component, producer_node=node.id)
    ctx.object_store.put_solid(handle, obj)
    ctx.bind_node_output(node.id, "body", solid_id)
    return solid_id


def _degraded_store(node: CanonicalNode, ctx: RuntimeContext, original_body, op_name: str) -> str:
    """Store original body when operation fails — logs warning, preserves geometry.

    v6.3: Required features hard fail — only optional/decorative features may degrade.
    """
    if getattr(node, "required", True):
        raise RuntimeError(
            f"Required operation '{op_name}' failed on '{node.id}': "
            f"operation cannot be skipped for required features. "
            f"Fix the parameters or mark the node as required=False."
        )
    ctx.warnings.append(
        f"'{op_name}' failed on '{node.id}': returning unmodified solid. "
        f"Part is valid without this operation."
    )
    return _store_solid(node, ctx, original_body)


# ═══════════════════════════════════════════════════════════════════════════════
# Transform handlers
# ═══════════════════════════════════════════════════════════════════════════════

def handle_translate_solid(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    vector = node.params.get("vector_mm", (0, 0, 0))
    if not (isinstance(vector, (list, tuple)) and len(vector) == 3):
        if getattr(node, "required", True):
            raise ValueError(
                f"required translate_solid on '{node.id}': "
                f"invalid vector_mm (expected 3D tuple, got {type(vector).__name__})"
            )
        ctx.warnings.append(f"translate_solid on '{node.id}': invalid vector, using (0,0,0)")
        vector = (0, 0, 0)
    if all(v == 0 for v in vector):
        if getattr(node, "required", True):
            ctx.warnings.append(
                f"translate_solid on '{node.id}': zero vector — no-op translation"
            )
        return {"body": _store_solid(node, ctx, body)}  # no-op
    try:
        return {"body": _store_solid(node, ctx, body.translate(vector))}
    except Exception as e:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required translate_solid failed on '{node.id}': {e}"
            ) from e
        ctx.warnings.append(f"translate_solid failed on '{node.id}': {e}")
        return {"body": _store_solid(node, ctx, body)}


def handle_rotate_solid(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    origin = node.params.get("axis_origin_mm", (0, 0, 0))
    axis_dir = node.params.get("axis_dir", (0, 0, 1))
    angle = float(node.params.get("angle_deg", 0))
    if angle == 0:
        if getattr(node, "required", True):
            ctx.warnings.append(
                f"rotate_solid on '{node.id}': angle=0deg — no-op rotation"
            )
        return {"body": _store_solid(node, ctx, body)}
    # Guard zero axis
    axis = tuple(float(x) for x in axis_dir) if isinstance(axis_dir, (list, tuple)) else (0, 0, 1)
    if all(v == 0 for v in axis):
        if getattr(node, "required", True):
            raise ValueError(
                f"required rotate_solid on '{node.id}': zero axis vector"
            )
        ctx.warnings.append(f"rotate_solid on '{node.id}': zero axis vector, skipping")
        return {"body": _store_solid(node, ctx, body)}
    try:
        return {"body": _store_solid(node, ctx, body.rotate(origin, axis, angle))}
    except Exception as e:
        return {"body": _degraded_store(node, ctx, body, "rotate_solid")}


def handle_place_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    """Place a component at the specified position.

    v6.3: Priority order for placement:
      1. ctx.spatial_placements[target_component_id] (ConstraintResolver output)
      2. node.params["position_mm"] (LLM-provided fallback)

    The ConstraintResolver runs after all leaf components are built and
    computes numeric placements from symbolic constraints + actual bboxes.
    This handler now consumes those computed placements.
    """
    body = resolve_input_object(node, ctx, 0)

    # ── v6.3: Preferred path — solver-computed placement ──
    pos = None
    placements = getattr(ctx, 'spatial_placements', None)
    if placements:
        # Determine target component ID:
        # 1. Explicit component_id param (v6.3)
        # 2. producer_component of first input (the solid being placed)
        target_cid = node.params.get("component_id")
        if not target_cid and node.inputs:
            target_cid = node.inputs[0].producer_component

        if target_cid and target_cid in placements:
            p = placements[target_cid]
            if not p.is_pending:
                pos = tuple(p.translation_mm)
                if p.rotation_deg_xyz and any(v != 0 for v in p.rotation_deg_xyz):
                    ctx.warnings.append(
                        f"place_component on '{node.id}': rotation from solver "
                        f"({p.rotation_deg_xyz}) ignored — rotation not yet "
                        f"supported in place_component handler"
                    )

    # ── Fallback: LLM-provided position ──
    if pos is None:
        pos = node.params.get("position_mm", (0, 0, 0))

    if not isinstance(pos, (list, tuple)) or len(pos) != 3:
        raise ValueError(f"place_component requires 3D position, got {pos}")

    pos_f = tuple(float(v) for v in pos)

    try:
        placed = body.translate(pos_f)
    except Exception as exc:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required place_component failed on '{node.id}': {exc}"
            ) from exc
        return {"body": _degraded_store(node, ctx, body, "place_component")}

    # ── v6.3: Track placed bbox for downstream spatial audit ──
    target_cid = node.params.get("component_id") or (
        node.inputs[0].producer_component if node.inputs else None
    )
    if target_cid and hasattr(ctx, "placed_component_bboxes"):
        try:
            bb = placed.val().BoundingBox() if hasattr(placed, 'val') else placed.BoundingBox()
            ctx.placed_component_bboxes[target_cid] = bb
        except Exception:
            pass

    return {"body": _store_solid(node, ctx, placed)}


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern handlers
# ═══════════════════════════════════════════════════════════════════════════════

def handle_circular_pattern_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    count = max(1, int(node.params.get("count", 1)))
    radius = float(node.params.get("radius_mm", 0))
    start_angle = float(node.params.get("start_angle_deg", 0))

    if count <= 1 or radius <= 0:
        msg = f"circular_pattern on '{node.id}': count={count} radius={radius} — invalid params"
        if getattr(node, "required", True):
            raise ValueError(msg)
        ctx.warnings.append(msg)
        return {"body": _store_solid(node, ctx, body)}

    rotate = bool(node.params.get("rotate_copies", True))
    try:
        import cadquery as cq
        result = None
        for i in range(count):  # include i=0, all copies properly placed
            angle_deg = start_angle + i * 360.0 / count
            angle = math.radians(angle_deg)
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            placed = body
            if rotate:
                placed = placed.rotate((0, 0, 0), (0, 0, 1), angle_deg)
            placed = placed.translate((x, y, 0))
            if result is None:
                result = placed
            else:
                result = result.union(placed)
        return {"body": _store_solid(node, ctx, result)}
    except Exception as e:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required circular_pattern failed on '{node.id}': {e}"
            ) from e
        ctx.warnings.append(f"circular_pattern failed on '{node.id}': {e}")
        return {"body": _store_solid(node, ctx, body)}


def handle_linear_pattern_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    count = max(1, int(node.params.get("count", 1)))
    spacing = float(node.params.get("spacing_mm", 0))
    direction = node.params.get("direction", "X")

    if count <= 1 or spacing <= 0:
        msg = f"linear_pattern on '{node.id}': count={count} spacing={spacing} — invalid params"
        if getattr(node, "required", True):
            raise ValueError(msg)
        ctx.warnings.append(msg)
        return {"body": _store_solid(node, ctx, body)}

    dir_map = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}
    dir_vec = dir_map.get(direction, (1, 0, 0))

    try:
        result = body
        for i in range(1, count):
            vec = tuple(spacing * i * d for d in dir_vec)
            result = result.union(body.translate(vec))
        return {"body": _store_solid(node, ctx, result)}
    except Exception as e:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required linear_pattern failed on '{node.id}': {e}"
            ) from e
        ctx.warnings.append(f"linear_pattern failed on '{node.id}': {e}")
        return {"body": _store_solid(node, ctx, body)}


# ═══════════════════════════════════════════════════════════════════════════════
# Boolean handlers
# ═══════════════════════════════════════════════════════════════════════════════

def handle_boolean_union(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    """Boolean union with three-layer fallback for OCCT stability.

    Attempt 1: CadQuery a.union(b)
    Attempt 2: OCCT BRepAlgoAPI_Fuse via a.fuse(b)
    Attempt 3 (v6.1): tolerance-expanded fuse for near-tangent/grazing contact
    Degradation: return first solid with detailed diagnostic record

    v6.1 adds Attempt 3 to handle thin-wall tube + shaft unions (tm07_roller)
    and other cases where OCCT boolean ops fail on grazing contact.
    """
    if len(node.inputs) != 2:
        raise ValueError(f"boolean_union requires exactly 2 inputs, got {len(node.inputs)}")
    a = resolve_input_object(node, ctx, 0)
    b = resolve_input_object(node, ctx, 1)

    # Pre-boolean diagnostic
    from seekflow_engineering_tools.generative_cad.validation.geometry_validate import pre_boolean_check
    pre = pre_boolean_check(a, b, ctx.tolerance)
    if pre.reason:
        ctx.warnings.append(f"boolean_union pre-check on '{node.id}': {pre.reason}")

    # ── Attempt 1: CadQuery union ──
    try:
        result = a.union(b)
        # Verify: check if result is still multi-solid
        if hasattr(result, 'Solids'):
            n_result = len(list(result.Solids()))
            n_a = len(list(a.Solids())) if hasattr(a, 'Solids') else 1
            n_b = len(list(b.Solids())) if hasattr(b, 'Solids') else 1
            if n_result < n_a + n_b:
                return _finish_boolean_op(node, ctx, result, "boolean_union")
            ctx.warnings.append(
                f"boolean_union: CadQuery union produced {n_result} solids "
                f"(a={n_a}, b={n_b}) — trying fuse"
            )
        else:
            return _finish_boolean_op(node, ctx, result, "boolean_union")
    except Exception:
        pass

    # ── Attempt 2: OCCT BRepAlgoAPI_Fuse ──
    try:
        result = a.fuse(b)
        if hasattr(result, 'Solids'):
            n_result = len(list(result.Solids()))
            n_a = len(list(a.Solids())) if hasattr(a, 'Solids') else 1
            n_b = len(list(b.Solids())) if hasattr(b, 'Solids') else 1
            if n_result < n_a + n_b:
                ctx.warnings.append(
                    f"boolean_union: OCCT fuse succeeded ({n_result} solids)"
                )
                return _finish_boolean_op(node, ctx, result, "boolean_union")
            ctx.warnings.append(
                f"boolean_union: OCCT fuse produced {n_result} solids "
                f"(expected < {n_a + n_b}) — trying tolerance-expanded fuse"
            )
        else:
            return _finish_boolean_op(node, ctx, result, "boolean_union")
    except Exception:
        pass

    # ── Attempt 3 (v6.3): OCCT fuzzy fuse — no geometry movement ──
    # Replaces the old translate-margin hack which moved solid B.
    # Uses SetFuzzyValue() for proper tolerance-based coincidence detection.
    try:
        from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.boolean_safe import (
            boolean_union_safe,
        )
        result, _strategy = boolean_union_safe(a, b, ctx.tolerance, allow_compound=False)
        ctx.warnings.append(
            f"boolean_union: fuzzy fuse succeeded "
            f"(clearance={_fmt_clr(pre.clearance_mm)})"
        )
        return _finish_boolean_op(node, ctx, result, "boolean_union")
    except Exception:
        pass

    # ── Degradation: HARD FAIL for required boolean_union ──
    # v6.3: boolean_union is a structurally critical operation.
    # Silently dropping solid B means the assembly is INCOMPLETE.
    # This is no longer allowed — we must fail-closed.
    ctx.degraded_features.append({
        "node_id": node.id, "op": "boolean_union",
        "reason": "all_fuse_strategies_failed",
        "clearance_mm": pre.clearance_mm,
        "lost_volume_mm3": pre.b_volume_mm3,
        "lost_bbox_mm": pre.b_bbox_mm,
        "kept_volume_mm3": pre.a_volume_mm3,
    })
    raise RuntimeError(
        f"boolean_union FAILED on '{node.id}': "
        f"Could not merge solid B ({_fmt_vol(pre.b_volume_mm3)}) with solid A "
        f"({_fmt_vol(pre.a_volume_mm3)}). "
        f"Clearance={_fmt_clr(pre.clearance_mm)}. "
        f"Check for non-intersecting geometry or grazing contact."
    )


def handle_boolean_cut(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    if len(node.inputs) != 2:
        raise ValueError(f"boolean_cut requires exactly 2 inputs, got {len(node.inputs)}")
    target = resolve_input_object(node, ctx, 0)
    tool = resolve_input_object(node, ctx, 1)

    from seekflow_engineering_tools.generative_cad.validation.geometry_validate import pre_boolean_check
    pre = pre_boolean_check(target, tool, ctx.tolerance)

    try:
        result = target.cut(tool)
    except Exception:
        try:
            result = target.cut(tool, ctx.tolerance.boolean_fallback_tolerance)
        except Exception:
            ctx.degraded_features.append({
                "node_id": node.id, "op": "boolean_cut",
                "reason": "cut_failed",
                "clearance_mm": pre.clearance_mm,
                "target_volume_mm3": pre.a_volume_mm3,
                "tool_volume_mm3": pre.b_volume_mm3,
            })
            raise RuntimeError(
                f"boolean_cut FAILED on '{node.id}': "
                f"cut was NOT applied. "
                f"Target={_fmt_vol(pre.a_volume_mm3)}, "
                f"Tool={_fmt_vol(pre.b_volume_mm3)}. "
                f"Clearance={_fmt_clr(pre.clearance_mm)}."
            )
    return _finish_boolean_op(node, ctx, result, "boolean_cut")


def _try_produce_boolean_topology(
    *, node: CanonicalNode, ctx: RuntimeContext, solid, op_name: str,
) -> None:
    """Phase 5: Build topology delta for boolean result faces."""
    try:
        from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
            build_entity_records_from_delta, name_boolean_faces,
        )
    except ImportError:
        return
    try:
        doc_id = getattr(node, "component", "unknown") or "unknown"
        delta = name_boolean_faces(
            solid, document_id=doc_id,
            component_id=node.component or "unknown",
            producer_node_id=node.id,
        )
        records = build_entity_records_from_delta(delta, document_id=doc_id)
        for rec in records:
            ctx.topology_registry.register_entity(rec)
        ctx.topology_registry.apply_delta(delta)
        ctx.topology_events.append({
            "event": "boolean_topology_produced",
            "node_id": node.id, "op": op_name,
            "face_count": len(delta.relations),
        })
    except Exception as exc:
        ctx.topology_warnings.append({
            "node_id": node.id, "phase": "boolean_topology", "op": op_name,
            "error": str(exc),
        })


def _finish_boolean_op(node, ctx, solid, op_name: str) -> dict[str, str]:
    """Store solid + produce topology delta, then return result map."""
    body_id = _store_solid(node, ctx, solid)
    _try_produce_boolean_topology(node=node, ctx=ctx, solid=solid, op_name=op_name)
    return {"body": body_id}


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_vol(v: float | None) -> str:
    return f"{v:.1f} mm³" if v is not None else "unknown"


def _fmt_clr(c: float | None) -> str:
    return f"{c:.3f} mm" if c is not None else "unknown"
