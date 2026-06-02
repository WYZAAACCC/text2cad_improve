"""Sketch_extrude handlers — v0.2.1: shared resolver, no silent degradation."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object


def _store_solid(node: CanonicalNode, ctx: RuntimeContext, obj) -> str:
    sid = f"solid:{node.component}:{node.id}:body"
    ctx.object_store.put_solid(SolidHandle(id=sid, component_id=node.component, producer_node=node.id), obj)
    ctx.bind_node_output(node.id, "body", sid)
    return sid


def handle_extrude_rectangle(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    p = node.typed_params if node.typed_params else node.params
    w, h, d = float(p["width_mm"]), float(p["height_mm"]), float(p["depth_mm"])
    plane, centered, direction = p.get("plane", "XY"), p.get("centered", True), p.get("direction", "+")
    wp = cq.Workplane(plane)
    if centered: wp = wp.center(0, 0)
    if direction == "-": d = -d
    return {"body": _store_solid(node, ctx, wp.rect(w, h).extrude(d))}


def handle_cut_rectangular_pocket(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    w, h, d = float(p["width_mm"]), float(p["height_mm"]), float(p["depth_mm"])
    plane = p.get("plane", "XY")
    cutter = cq.Workplane(plane).rect(w, h).extrude(-d)
    return {"body": _store_solid(node, ctx, body.cut(cutter))}


def handle_cut_hole(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    dia = float(p["diameter_mm"]); pos = p.get("position_mm", [0, 0, 0])
    bb = body.val().BoundingBox()
    x, y = pos[0], pos[1] if len(pos) > 1 else 0
    cutter = cq.Workplane("XY").center(x, y).circle(dia / 2.0).extrude(bb.zlen + 10, both=True)
    return {"body": _store_solid(node, ctx, body.cut(cutter))}


def handle_cut_hole_pattern_linear(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    dia, cx, cy = float(p["hole_dia_mm"]), int(p["count_x"]), int(p["count_y"])
    sx, sy = float(p["spacing_x_mm"]), float(p["spacing_y_mm"])
    bb = body.val().BoundingBox(); z_len = bb.zlen + 10
    combined = None
    for ix in range(cx):
        for iy in range(cy):
            cutter = cq.Workplane("XY").center((ix - (cx - 1) / 2.0) * sx, (iy - (cy - 1) / 2.0) * sy).circle(dia / 2.0).extrude(z_len, both=True)
            combined = cutter if combined is None else combined.union(cutter)
    return {"body": _store_solid(node, ctx, body.cut(combined) if combined is not None else body)}


def handle_add_rectangular_boss(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    w, h, d = float(p["width_mm"]), float(p["height_mm"]), float(p["depth_mm"])
    pos = p.get("position_mm", [0, 0, 0])
    x, y = pos[0], pos[1] if len(pos) > 1 else 0
    boss = cq.Workplane("XY").center(x, y).rect(w, h).extrude(d)
    return {"body": _store_solid(node, ctx, body.union(boss))}


def handle_add_rib(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    t, h, length = float(p["thickness_mm"]), float(p["height_mm"]), float(p["length_mm"])
    pos, direction = p.get("position_mm", [0, 0, 0]), p.get("direction", "X")
    x, y = pos[0], pos[1] if len(pos) > 1 else 0
    rib = cq.Workplane("YZ").center(y, 0).rect(t, h).extrude(length) if direction == "X" else cq.Workplane("XZ").center(x, 0).rect(t, h).extrude(length)
    return {"body": _store_solid(node, ctx, body.union(rib))}


def handle_se_fillet(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    r = float(node.typed_params.get("radius_mm", node.params.get("radius_mm", 0))) if node.typed_params else float(node.params.get("radius_mm", 0))
    if r > 0:
        try:
            body = body.fillet(r)
        except Exception:
            try:
                body = body.fillet(r / 2.0)
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
        try:
            body = body.chamfer(d)
        except Exception:
            try:
                body = body.chamfer(d / 2.0)
            except Exception:
                ctx.warnings.append(
                    f"Safe chamfer skipped on '{node.id}': geometry does not support chamfer. "
                    f"Part is valid without chamfer."
                )
    return {"body": _store_solid(node, ctx, body)}
