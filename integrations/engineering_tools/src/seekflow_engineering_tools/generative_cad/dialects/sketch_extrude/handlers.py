"""Sketch_extrude operation handlers."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle


def _resolve_solid_input(node: CanonicalNode, ctx: RuntimeContext) -> str:
    if node.inputs and node.inputs[0].producer_node:
        return ctx.resolve_node_output(node.inputs[0].producer_node, node.inputs[0].output)
    return ctx.resolve_node_output(node.id, "body")


def _store_solid(node: CanonicalNode, ctx: RuntimeContext, obj) -> str:
    solid_id = f"solid:{node.component}:{node.id}:body"
    handle = SolidHandle(id=solid_id, component_id=node.component, producer_node=node.id)
    ctx.object_store.put_solid(handle, obj)
    ctx.bind_node_output(node.id, "body", solid_id)
    return solid_id


def handle_extrude_rectangle(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    p = node.params
    w, h, d = float(p["width_mm"]), float(p["height_mm"]), float(p["depth_mm"])
    plane = p.get("plane", "XY")
    centered = p.get("centered", True)
    direction = p.get("direction", "+")
    wp = cq.Workplane(plane)
    if centered:
        wp = wp.center(0, 0)
    rect = wp.rect(w, h)
    if direction == "-":
        d = -d
    result = rect.extrude(d)
    hid = _store_solid(node, ctx, result)
    return {"body": hid}


def handle_cut_rectangular_pocket(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    p = node.params
    w, h, d = float(p["width_mm"]), float(p["height_mm"]), float(p["depth_mm"])
    plane = p.get("plane", "XY")
    body = ctx.object_store.get(_resolve_solid_input(node, ctx))
    cutter = cq.Workplane(plane).rect(w, h).extrude(-d)
    result = body.cut(cutter)
    hid = _store_solid(node, ctx, result)
    return {"body": hid}


def handle_cut_hole(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    p = node.params
    dia = float(p["diameter_mm"])
    pos = p.get("position_mm", [0, 0, 0])
    body = ctx.object_store.get(_resolve_solid_input(node, ctx))
    bb = body.val().BoundingBox()
    z_len = bb.zlen + 10
    x, y = pos[0], pos[1] if len(pos) > 1 else 0
    cutter = cq.Workplane("XY").center(x, y).circle(dia / 2.0).extrude(z_len, both=True)
    result = body.cut(cutter)
    hid = _store_solid(node, ctx, result)
    return {"body": hid}


def handle_cut_hole_pattern_linear(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    p = node.params
    dia = float(p["hole_dia_mm"])
    cx, cy = int(p["count_x"]), int(p["count_y"])
    sx, sy = float(p["spacing_x_mm"]), float(p["spacing_y_mm"])
    body = ctx.object_store.get(_resolve_solid_input(node, ctx))
    bb = body.val().BoundingBox()
    z_len = bb.zlen + 10

    combined = None
    for ix in range(cx):
        for iy in range(cy):
            x_off = (ix - (cx - 1) / 2.0) * sx
            y_off = (iy - (cy - 1) / 2.0) * sy
            cutter = cq.Workplane("XY").center(x_off, y_off).circle(dia / 2.0).extrude(z_len, both=True)
            combined = cutter if combined is None else combined.union(cutter)

    result = body.cut(combined) if combined is not None else body
    hid = _store_solid(node, ctx, result)
    return {"body": hid}


def handle_add_rectangular_boss(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    p = node.params
    w, h, d = float(p["width_mm"]), float(p["height_mm"]), float(p["depth_mm"])
    pos = p.get("position_mm", [0, 0, 0])
    body = ctx.object_store.get(_resolve_solid_input(node, ctx))
    x, y = pos[0], pos[1] if len(pos) > 1 else 0
    boss = cq.Workplane("XY").center(x, y).rect(w, h).extrude(d)
    result = body.union(boss)
    hid = _store_solid(node, ctx, result)
    return {"body": hid}


def handle_add_rib(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    p = node.params
    t, h, length = float(p["thickness_mm"]), float(p["height_mm"]), float(p["length_mm"])
    pos = p.get("position_mm", [0, 0, 0])
    direction = p.get("direction", "X")
    body = ctx.object_store.get(_resolve_solid_input(node, ctx))
    x, y = pos[0], pos[1] if len(pos) > 1 else 0
    if direction == "X":
        rib = cq.Workplane("YZ").center(y, 0).rect(t, h).extrude(length)
    else:
        rib = cq.Workplane("XZ").center(x, 0).rect(t, h).extrude(length)
    result = body.union(rib)
    hid = _store_solid(node, ctx, result)
    return {"body": hid}


def handle_se_fillet(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = ctx.object_store.get(_resolve_solid_input(node, ctx))
    r = float(node.params.get("radius_mm", 0))
    if r > 0:
        try:
            body = body.fillet(r)
        except Exception:
            pass
    hid = _store_solid(node, ctx, body)
    return {"body": hid}


def handle_se_chamfer(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = ctx.object_store.get(_resolve_solid_input(node, ctx))
    d = float(node.params.get("distance_mm", 0))
    if d > 0:
        try:
            body = body.chamfer(d)
        except Exception:
            pass
    hid = _store_solid(node, ctx, body)
    return {"body": hid}
