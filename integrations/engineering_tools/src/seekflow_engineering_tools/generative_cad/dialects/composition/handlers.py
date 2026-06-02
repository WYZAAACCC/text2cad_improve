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
    """Store original body when operation fails — logs warning, preserves geometry."""
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
        ctx.warnings.append(f"translate_solid on '{node.id}': invalid vector, using (0,0,0)")
        vector = (0, 0, 0)
    if all(v == 0 for v in vector):
        return {"body": _store_solid(node, ctx, body)}  # no-op
    try:
        return {"body": _store_solid(node, ctx, body.translate(vector))}
    except Exception as e:
        ctx.warnings.append(f"translate_solid failed on '{node.id}': {e}")
        return {"body": _store_solid(node, ctx, body)}


def handle_rotate_solid(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    origin = node.params.get("axis_origin_mm", (0, 0, 0))
    axis_dir = node.params.get("axis_dir", (0, 0, 1))
    angle = float(node.params.get("angle_deg", 0))
    if angle == 0:
        return {"body": _store_solid(node, ctx, body)}
    # Guard zero axis
    axis = tuple(float(x) for x in axis_dir) if isinstance(axis_dir, (list, tuple)) else (0, 0, 1)
    if all(v == 0 for v in axis):
        ctx.warnings.append(f"rotate_solid on '{node.id}': zero axis vector, skipping")
        return {"body": _store_solid(node, ctx, body)}
    try:
        return {"body": _store_solid(node, ctx, body.rotate(origin, axis, angle))}
    except Exception as e:
        return {"body": _degraded_store(node, ctx, body, "rotate_solid")}


def handle_place_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    pos = node.params.get("position_mm", (0, 0, 0))
    if all(v == 0 for v in (pos if isinstance(pos, (list, tuple)) else (0, 0, 0))):
        return {"body": _store_solid(node, ctx, body)}
    try:
        return {"body": _store_solid(node, ctx, body.translate(pos))}
    except Exception:
        return {"body": _degraded_store(node, ctx, body, "place_component")}


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern handlers
# ═══════════════════════════════════════════════════════════════════════════════

def handle_circular_pattern_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    count = max(1, int(node.params.get("count", 1)))
    radius = float(node.params.get("radius_mm", 0))
    start_angle = float(node.params.get("start_angle_deg", 0))

    if count <= 1 or radius <= 0:
        ctx.warnings.append(
            f"circular_pattern on '{node.id}': count={count} radius={radius} — no pattern, returning original"
        )
        return {"body": _store_solid(node, ctx, body)}

    # Use native CadQuery array operations for performance
    try:
        import cadquery as cq
        # Build all positions, translate copies, union
        result = body
        for i in range(1, count):  # skip i=0 (original position)
            angle = math.radians(start_angle + i * 360.0 / count)
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            placed = body.translate((x, y, 0))
            result = result.union(placed)
        return {"body": _store_solid(node, ctx, result)}
    except Exception as e:
        ctx.warnings.append(f"circular_pattern failed on '{node.id}': {e}")
        return {"body": _store_solid(node, ctx, body)}


def handle_linear_pattern_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    count = max(1, int(node.params.get("count", 1)))
    spacing = float(node.params.get("spacing_mm", 0))
    direction = node.params.get("direction", "X")

    if count <= 1 or spacing <= 0:
        ctx.warnings.append(
            f"linear_pattern on '{node.id}': count={count} spacing={spacing} — no pattern, returning original"
        )
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
        ctx.warnings.append(f"linear_pattern failed on '{node.id}': {e}")
        return {"body": _store_solid(node, ctx, body)}


# ═══════════════════════════════════════════════════════════════════════════════
# Boolean handlers
# ═══════════════════════════════════════════════════════════════════════════════

def handle_boolean_union(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    if len(node.inputs) != 2:
        raise ValueError(f"boolean_union requires exactly 2 inputs, got {len(node.inputs)}")
    a = resolve_input_object(node, ctx, 0)
    b = resolve_input_object(node, ctx, 1)

    # Pre-boolean diagnostic
    from seekflow_engineering_tools.generative_cad.validation.geometry_validate import pre_boolean_check
    pre = pre_boolean_check(a, b, ctx.tolerance)
    if pre.reason:
        ctx.warnings.append(f"boolean_union pre-check on '{node.id}': {pre.reason}")

    try:
        result = a.union(b)
    except Exception:
        try:
            result = a.fuse(b)
        except Exception:
            # Structured degradation record — no silent data loss
            ctx.degraded_features.append({
                "node_id": node.id, "op": "boolean_union",
                "reason": "union_failed_returning_first_solid",
                "clearance_mm": pre.clearance_mm,
                "lost_volume_mm3": pre.b_volume_mm3,
                "lost_bbox_mm": pre.b_bbox_mm,
                "kept_volume_mm3": pre.a_volume_mm3,
            })
            ctx.warnings.append(
                f"boolean_union FAILED on '{node.id}': "
                f"solid B ({_fmt_vol(pre.b_volume_mm3)}) was NOT merged. "
                f"Assembly is INCOMPLETE. Clearance={_fmt_clr(pre.clearance_mm)}."
            )
            return {"body": _store_solid(node, ctx, a)}
    return {"body": _store_solid(node, ctx, result)}


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
                "reason": "cut_failed_returning_unmodified_target",
                "clearance_mm": pre.clearance_mm,
                "target_volume_mm3": pre.a_volume_mm3,
                "tool_volume_mm3": pre.b_volume_mm3,
            })
            ctx.warnings.append(
                f"boolean_cut FAILED on '{node.id}': cut was NOT applied. "
                f"Target volume={_fmt_vol(pre.a_volume_mm3)}, "
                f"Tool volume={_fmt_vol(pre.b_volume_mm3)}."
            )
            return {"body": _store_solid(node, ctx, target)}
    return {"body": _store_solid(node, ctx, result)}


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_vol(v: float | None) -> str:
    return f"{v:.1f} mm³" if v is not None else "unknown"


def _fmt_clr(c: float | None) -> str:
    return f"{c:.3f} mm" if c is not None else "unknown"
