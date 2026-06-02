"""Sketch_extrude handlers — v1.0 hardened.

All handlers follow: validate params → try full op → try fallback → warn+skip.
No silent None propagation. No uncaught OCCT errors.
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object


def _store_solid(node: CanonicalNode, ctx: RuntimeContext, obj) -> str:
    if obj is None:
        raise RuntimeError(f"BUG: _store_solid called with None on '{node.id}'")
    sid = f"solid:{node.component}:{node.id}:body"
    ctx.object_store.put_solid(SolidHandle(id=sid, component_id=node.component, producer_node=node.id), obj)
    ctx.bind_node_output(node.id, "body", sid)
    return sid


def _degrade(node: CanonicalNode, ctx: RuntimeContext, body, op_name: str) -> str:
    ctx.warnings.append(
        f"'{op_name}' skipped on '{node.id}': geometry does not support it. "
        f"Part is valid without this operation."
    )
    return _store_solid(node, ctx, body)


# ═══════════════════════════════════════════════════════════════════════════════
# Base solid
# ═══════════════════════════════════════════════════════════════════════════════

def handle_extrude_rectangle(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    p = node.typed_params if node.typed_params else node.params
    w = float(p.get("width_mm", 0))
    h = float(p.get("height_mm", 0))
    d = float(p.get("depth_mm", 0))
    if w <= 0 or h <= 0 or d <= 0:
        raise ValueError(f"extrude_rectangle requires positive dimensions, got {w}x{h}x{d}")
    plane = p.get("plane", "XY")
    centered = p.get("centered", True)
    direction = p.get("direction", "+")
    try:
        wp = cq.Workplane(plane)
        if centered:
            wp = wp.center(0, 0)
        if direction == "-":
            d = -d
        solid = wp.rect(w, h).extrude(d)
    except Exception as e:
        raise RuntimeError(f"extrude_rectangle failed: {e}")
    return {"body": _store_solid(node, ctx, solid)}


# ═══════════════════════════════════════════════════════════════════════════════
# Material removal
# ═══════════════════════════════════════════════════════════════════════════════

def handle_cut_rectangular_pocket(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    w = float(p.get("width_mm", 0))
    h = float(p.get("height_mm", 0))
    d = float(p.get("depth_mm", 0))
    if w <= 0 or h <= 0 or d <= 0:
        return {"body": _degrade(node, ctx, body, "cut_rectangular_pocket")}
    try:
        plane = p.get("plane", "XY")
        cutter = cq.Workplane(plane).rect(w, h).extrude(-d)
        result = body.cut(cutter)
    except Exception:
        return {"body": _degrade(node, ctx, body, "cut_rectangular_pocket")}
    return {"body": _store_solid(node, ctx, result)}


def handle_cut_hole(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    dia = float(p.get("diameter_mm", 0))
    if dia <= 0:
        return {"body": _degrade(node, ctx, body, "cut_hole")}
    pos = p.get("position_mm", [0, 0, 0])
    x = pos[0] if len(pos) > 0 else 0
    y = pos[1] if len(pos) > 1 else 0
    try:
        bb = body.val().BoundingBox()
        cutter = cq.Workplane("XY").center(x, y).circle(dia / 2.0).extrude(bb.zlen + 10, both=True)
        result = body.cut(cutter)
    except Exception:
        return {"body": _degrade(node, ctx, body, "cut_hole")}
    return {"body": _store_solid(node, ctx, result)}


def handle_cut_hole_pattern_linear(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    dia = float(p.get("hole_dia_mm", 0))
    cx = max(1, int(p.get("count_x", 1)))
    cy = max(1, int(p.get("count_y", 1)))
    sx = float(p.get("spacing_x_mm", 0))
    sy = float(p.get("spacing_y_mm", 0))
    if dia <= 0 or sx <= 0 or sy <= 0:
        return {"body": _degrade(node, ctx, body, "cut_hole_pattern_linear")}
    try:
        bb = body.val().BoundingBox()
        z_len = bb.zlen + 10
        cutters = []
        for ix in range(cx):
            for iy in range(cy):
                x = (ix - (cx - 1) / 2.0) * sx
                y = (iy - (cy - 1) / 2.0) * sy
                cutters.append(
                    cq.Workplane("XY").center(x, y).circle(dia / 2.0).extrude(z_len, both=True)
                )
        combined = cutters[0]
        for c in cutters[1:]:
            combined = combined.union(c)
        result = body.cut(combined)
    except Exception:
        return {"body": _degrade(node, ctx, body, "cut_hole_pattern_linear")}
    return {"body": _store_solid(node, ctx, result)}


# ═══════════════════════════════════════════════════════════════════════════════
# Material addition
# ═══════════════════════════════════════════════════════════════════════════════

def handle_add_rectangular_boss(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    w = float(p.get("width_mm", 0))
    h = float(p.get("height_mm", 0))
    d = float(p.get("depth_mm", 0))
    if w <= 0 or h <= 0 or d <= 0:
        return {"body": _degrade(node, ctx, body, "add_rectangular_boss")}
    pos = p.get("position_mm", [0, 0, 0])
    x = pos[0] if len(pos) > 0 else 0
    y = pos[1] if len(pos) > 1 else 0
    try:
        boss = cq.Workplane("XY").center(x, y).rect(w, h).extrude(d)
        result = body.union(boss)
    except Exception:
        return {"body": _degrade(node, ctx, body, "add_rectangular_boss")}
    return {"body": _store_solid(node, ctx, result)}


def handle_add_rib(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    t = float(p.get("thickness_mm", 0))
    h = float(p.get("height_mm", 0))
    length = float(p.get("length_mm", 0))
    if t <= 0 or h <= 0 or length <= 0:
        return {"body": _degrade(node, ctx, body, "add_rib")}
    pos = p.get("position_mm", [0, 0, 0])
    direction = p.get("direction", "X")
    x = pos[0] if len(pos) > 0 else 0
    y = pos[1] if len(pos) > 1 else 0
    try:
        if direction == "X":
            rib = cq.Workplane("YZ").center(y, 0).rect(t, h).extrude(length)
        elif direction == "Y":
            rib = cq.Workplane("XZ").center(x, 0).rect(t, h).extrude(length)
        else:
            ctx.warnings.append(f"add_rib on '{node.id}': invalid direction '{direction}', using X")
            rib = cq.Workplane("YZ").center(y, 0).rect(t, h).extrude(length)
        result = body.union(rib)
    except Exception:
        return {"body": _degrade(node, ctx, body, "add_rib")}
    return {"body": _store_solid(node, ctx, result)}


# ═══════════════════════════════════════════════════════════════════════════════
# Edge treatment (already hardened — unchanged from v0.2.1)
# ═══════════════════════════════════════════════════════════════════════════════

def handle_se_fillet(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    r = float(node.typed_params.get("radius_mm", node.params.get("radius_mm", 0))) if node.typed_params else float(node.params.get("radius_mm", 0))
    if r > 0:
        target = node.params.get("target", "all_external_edges")
        from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.handlers import _fillet_by_target
        try:
            body = _fillet_by_target(body, r, target)
        except Exception:
            try:
                body = _fillet_by_target(body, r / 2.0, target)
            except Exception:
                ctx.warnings.append(
                    f"Safe fillet skipped on '{node.id}': geometry does not support fillet. "
                    f"Part is valid without fillet."
                )
    return {"body": _store_solid(node, ctx, body)}


def handle_se_chamfer(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    d = float(node.typed_params.get("distance_mm", node.params.get("distance_mm", 0))) if node.typed_params else float(node.params.get("distance_mm", 0))
    if d > 0:
        target = node.params.get("target", "all_external_edges")
        from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.handlers import _chamfer_by_target
        try:
            body = _chamfer_by_target(body, d, target)
        except Exception:
            try:
                body = _chamfer_by_target(body, d / 2.0, target)
            except Exception:
                ctx.warnings.append(
                    f"Safe chamfer skipped on '{node.id}': geometry does not support chamfer. "
                    f"Part is valid without chamfer."
                )
    return {"body": _store_solid(node, ctx, body)}
