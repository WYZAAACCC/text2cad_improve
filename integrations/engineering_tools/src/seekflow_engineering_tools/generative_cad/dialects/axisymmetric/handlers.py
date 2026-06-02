"""Axisymmetric dialect handlers — v0.2.1: shared resolver, no silent degradation."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle, FrameHandle
from seekflow_engineering_tools.generative_cad.runtime.resolve import (
    resolve_input_object,
    resolve_input_handle_id,
)


def _store_solid(node: CanonicalNode, ctx: RuntimeContext, obj) -> str:
    sid = f"solid:{node.component}:{node.id}:body"
    ctx.object_store.put_solid(SolidHandle(id=sid, component_id=node.component, producer_node=node.id), obj)
    ctx.bind_node_output(node.id, "body", sid)
    return sid


def handle_revolve_profile(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    stations = node.typed_params.get("profile_stations", node.params.get("profile_stations", []))
    if len(stations) < 2:
        raise ValueError("Need at least 2 profile stations")

    pts_2d: list[tuple[float, float]] = []
    for s in stations:
        pts_2d.append((float(s["r_mm"]), float(s.get("z_front_mm", 0))))
        pts_2d.append((float(s["r_mm"]), float(s.get("z_rear_mm", 0))))
    # Sort by z only (stable sort preserves input order for same z).
    # Using (p[1], p[0]) was WRONG — sorting by r within same z
    # destroyed the sequential profile wire, producing zero-volume revolve.
    pts_2d.sort(key=lambda p: p[1])

    # Deduplicate consecutive identical points (prevent degenerate zero-length edges)
    unique_pts = [pts_2d[0]]
    for pt in pts_2d[1:]:
        if pt != unique_pts[-1]:
            unique_pts.append(pt)

    # Build a proper axisymmetric revolve.
    # Profile is on XZ plane (X=radius, Z=height). Must start from Z axis
    # (r=0) at the bottom, trace the outer profile, return to Z axis at
    # the top, then close. Use default revolve() — explicit axis (0,0,0)-(0,0,1)
    # produces zero-volume on XZ workplane due to CadQuery internal behavior.
    z_min = unique_pts[0][1]
    z_max = unique_pts[-1][1]
    result = cq.Workplane("XZ").moveTo(0, z_min)
    for (r, z) in unique_pts:
        result = result.lineTo(r, z)
    result = result.lineTo(0, z_max).close()
    solid = result.revolve(360)

    result_map = {}
    sid = _store_solid(node, ctx, solid)
    result_map["body"] = sid

    if any(o.name == "outer_frame" for o in node.outputs):
        fid = f"frame:{node.component}:{node.id}:outer_frame"
        ctx.object_store.put_frame(FrameHandle(id=fid, component_id=node.component, producer_node=node.id))
        ctx.bind_node_output(node.id, "outer_frame", fid)
        result_map["outer_frame"] = fid
    return result_map


def handle_cut_center_bore(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    dia = float(node.typed_params.get("diameter_mm", node.params.get("diameter_mm", 0)))
    if dia <= 0:
        raise ValueError("diameter_mm must be positive")
    bb = body.val().BoundingBox()
    bore = cq.Workplane("XY").circle(dia / 2.0).extrude(bb.zlen + 10, both=True)
    result = body.cut(bore)
    return {"body": _store_solid(node, ctx, result)}


def handle_cut_circular_hole_pattern(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    import math
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    count, pcd, hole_dia = int(p["count"]), float(p["pcd_mm"]), float(p["hole_dia_mm"])
    if count < 2 or pcd <= 0 or hole_dia <= 0:
        raise ValueError("count, pcd_mm, hole_dia_mm must be valid")
    bb = body.val().BoundingBox()
    z_len = bb.zlen + 10
    combined = None
    for i in range(count):
        angle = math.radians(i * 360.0 / count)
        x, y = (pcd / 2.0) * math.cos(angle), (pcd / 2.0) * math.sin(angle)
        cutter = cq.Workplane("XY").center(x, y).circle(hole_dia / 2.0).extrude(z_len, both=True)
        combined = cutter if combined is None else combined.union(cutter)
    result = body.cut(combined) if combined is not None else body
    return {"body": _store_solid(node, ctx, result)}


def handle_cut_annular_groove(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    inner, outer, depth = float(p["inner_dia_mm"]), float(p["outer_dia_mm"]), float(p["depth_mm"])
    side = p.get("side", "front")
    bb = body.val().BoundingBox()
    z_pos = bb.zmax if side == "front" else bb.zmin
    extrude_dir = -depth if side == "front" else depth
    ring = cq.Workplane("XY").workplane(offset=z_pos).circle(outer / 2.0).circle(inner / 2.0).extrude(extrude_dir)
    return {"body": _store_solid(node, ctx, body.cut(ring))}


def handle_cut_rim_slot_pattern(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    import math
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    count, slot_depth = int(p["count"]), float(p["slot_depth_mm"])
    profile = p.get("slot_profile", {})
    stations = profile.get("stations", [])
    if count < 2 or slot_depth <= 0 or len(stations) < 2:
        raise ValueError("Invalid slot parameters")
    bb = body.val().BoundingBox()
    outer_r = max(bb.xlen, bb.ylen) / 2.0
    slot_pts: list[tuple[float, float]] = [(outer_r, 0)]
    for s in stations:
        sd, hw = float(s["depth_mm"]), float(s["half_width_mm"])
        slot_pts.append((outer_r - sd, hw))
        slot_pts.append((outer_r - sd, -hw))
    slot_pts.append((outer_r, 0))
    wp = cq.Workplane("XY")
    for i, (r, w) in enumerate(slot_pts):
        wp = wp.moveTo(r, w) if i == 0 else wp.lineTo(r, w)
    cutter = wp.close().extrude(bb.zlen + 10, both=True)
    combined = None
    for i in range(count):
        angle = math.degrees(i * 2 * math.pi / count)
        c = cutter.rotate((0, 0, 0), (0, 0, 1), angle)
        combined = c if combined is None else combined.union(c)
    return {"body": _store_solid(node, ctx, body.cut(combined) if combined is not None else body)}


def handle_apply_safe_chamfer(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    distance = float(node.typed_params.get("distance_mm", node.params.get("distance_mm", 0)))
    if distance > 0:
        body = body.chamfer(distance)
    return {"body": _store_solid(node, ctx, body)}
