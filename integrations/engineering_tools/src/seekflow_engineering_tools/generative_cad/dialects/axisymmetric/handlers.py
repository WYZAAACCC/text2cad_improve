"""Axisymmetric dialect operation handlers — typed, object-store based."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle


def handle_revolve_profile(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq

    params = node.params
    stations = params.get("profile_stations", [])
    if len(stations) < 2:
        raise ValueError("Need at least 2 profile stations")

    pts_2d: list[tuple[float, float]] = []
    for s in stations:
        r = float(s["r_mm"])
        z_front = float(s.get("z_front_mm", 0))
        z_rear = float(s.get("z_rear_mm", 0))
        pts_2d.append((r, z_front))
        pts_2d.append((r, z_rear))

    pts_2d.sort(key=lambda p: (p[1], p[0]))
    result = cq.Workplane("XZ").moveTo(pts_2d[0][0], pts_2d[0][1])
    for (r, z) in pts_2d[1:]:
        result = result.lineTo(r, z)
    last_r, last_z = pts_2d[-1]
    first_r, first_z = pts_2d[0]
    result = result.lineTo(0, last_z).lineTo(0, first_z).close()
    result = result.revolve(360, (0, 0, 0), (0, 0, 1))

    solid_id = f"solid:{node.component}:{node.id}:body"
    handle = SolidHandle(id=solid_id, component_id=node.component, producer_node=node.id)
    ctx.object_store.put_solid(handle, result)
    ctx.bind_node_output(node.id, "body", solid_id)

    frame_id = f"frame:{node.component}:{node.id}:outer_frame"
    from seekflow_engineering_tools.generative_cad.runtime.handles import FrameHandle
    fh = FrameHandle(id=frame_id, component_id=node.component, producer_node=node.id)
    ctx.object_store.put_frame(fh)
    ctx.bind_node_output(node.id, "outer_frame", frame_id)

    result_map = {"body": solid_id}
    if "outer_frame" in [o.name for o in node.outputs]:
        result_map["outer_frame"] = frame_id
    return result_map


def handle_cut_center_bore(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq

    input_handle_id = ctx.resolve_node_output(node.id, "body") if node.inputs else None
    if node.inputs and input_handle_id is None:
        if node.inputs and node.inputs[0].producer_node:
            input_handle_id = ctx.resolve_node_output(node.inputs[0].producer_node, node.inputs[0].output)

    body = ctx.object_store.get(input_handle_id)
    dia = float(node.params.get("diameter_mm", 0))
    if dia <= 0:
        raise ValueError("diameter_mm must be positive")

    bb = body.val().BoundingBox()
    z_len = bb.zlen + 10
    bore = cq.Workplane("XY").circle(dia / 2.0).extrude(z_len, both=True)
    result = body.cut(bore)

    solid_id = f"solid:{node.component}:{node.id}:body"
    handle = SolidHandle(id=solid_id, component_id=node.component, producer_node=node.id)
    ctx.object_store.put_solid(handle, result)
    ctx.bind_node_output(node.id, "body", solid_id)
    return {"body": solid_id}


def handle_cut_circular_hole_pattern(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    import math

    if node.inputs and node.inputs[0].producer_node:
        input_handle_id = ctx.resolve_node_output(node.inputs[0].producer_node, node.inputs[0].output)
    else:
        input_handle_id = ctx.resolve_node_output(node.id, "body")
    body = ctx.object_store.get(input_handle_id)

    count = int(node.params.get("count", 0))
    pcd = float(node.params.get("pcd_mm", 0))
    hole_dia = float(node.params.get("hole_dia_mm", 0))
    if count < 2 or pcd <= 0 or hole_dia <= 0:
        raise ValueError("count, pcd_mm, hole_dia_mm must be valid")

    bb = body.val().BoundingBox()
    z_len = bb.zlen + 10
    combined = None
    for i in range(count):
        angle = math.radians(i * 360.0 / count)
        x = (pcd / 2.0) * math.cos(angle)
        y = (pcd / 2.0) * math.sin(angle)
        cutter = cq.Workplane("XY").center(x, y).circle(hole_dia / 2.0).extrude(z_len, both=True)
        if combined is None:
            combined = cutter
        else:
            combined = combined.union(cutter)

    result = body.cut(combined) if combined is not None else body
    solid_id = f"solid:{node.component}:{node.id}:body"
    handle = SolidHandle(id=solid_id, component_id=node.component, producer_node=node.id)
    ctx.object_store.put_solid(handle, result)
    ctx.bind_node_output(node.id, "body", solid_id)
    return {"body": solid_id}


def handle_cut_annular_groove(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq

    if node.inputs and node.inputs[0].producer_node:
        input_handle_id = ctx.resolve_node_output(node.inputs[0].producer_node, node.inputs[0].output)
    else:
        input_handle_id = ctx.resolve_node_output(node.id, "body")
    body = ctx.object_store.get(input_handle_id)

    inner = float(node.params.get("inner_dia_mm", 0))
    outer = float(node.params.get("outer_dia_mm", 0))
    depth = float(node.params.get("depth_mm", 0))
    side = node.params.get("side", "front")

    bb = body.val().BoundingBox()
    z_pos = bb.zmax if side == "front" else bb.zmin
    extrude_dir = -depth if side == "front" else depth

    groove_ring = (
        cq.Workplane("XY").workplane(offset=z_pos)
        .circle(outer / 2.0).circle(inner / 2.0)
        .extrude(extrude_dir)
    )
    result = body.cut(groove_ring)

    solid_id = f"solid:{node.component}:{node.id}:body"
    handle = SolidHandle(id=solid_id, component_id=node.component, producer_node=node.id)
    ctx.object_store.put_solid(handle, result)
    ctx.bind_node_output(node.id, "body", solid_id)
    return {"body": solid_id}


def handle_cut_rim_slot_pattern(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    import math

    if node.inputs and node.inputs[0].producer_node:
        input_handle_id = ctx.resolve_node_output(node.inputs[0].producer_node, node.inputs[0].output)
    else:
        input_handle_id = ctx.resolve_node_output(node.id, "body")
    body = ctx.object_store.get(input_handle_id)

    count = int(node.params.get("count", 0))
    slot_depth = float(node.params.get("slot_depth_mm", 0))
    profile = node.params.get("slot_profile", {})
    stations = profile.get("stations", [])

    if count < 2 or slot_depth <= 0 or len(stations) < 2:
        raise ValueError("Invalid slot parameters")

    bb = body.val().BoundingBox()
    outer_r = max(bb.xlen, bb.ylen) / 2.0
    bb_z = bb.zlen + 10

    slot_pts: list[tuple[float, float]] = [(outer_r, 0)]
    for s in stations:
        sd = float(s.get("depth_mm", 0))
        hw = float(s.get("half_width_mm", 0))
        r_at_depth = outer_r - sd
        slot_pts.append((r_at_depth, hw))
        slot_pts.append((r_at_depth, -hw))
    slot_pts.append((outer_r, 0))

    slot_wp = cq.Workplane("XY")
    for i, (r, w) in enumerate(slot_pts):
        if i == 0:
            slot_wp = slot_wp.moveTo(r, w)
        else:
            slot_wp = slot_wp.lineTo(r, w)
    slot_wp = slot_wp.close()
    slot_cutter = slot_wp.extrude(bb_z, both=True)

    combined = None
    for i in range(count):
        angle = math.radians(i * 360.0 / count)
        rotated = slot_cutter.rotate((0, 0, 0), (0, 0, 1), math.degrees(angle))
        combined = rotated if combined is None else combined.union(rotated)

    result = body.cut(combined) if combined is not None else body
    solid_id = f"solid:{node.component}:{node.id}:body"
    handle = SolidHandle(id=solid_id, component_id=node.component, producer_node=node.id)
    ctx.object_store.put_solid(handle, result)
    ctx.bind_node_output(node.id, "body", solid_id)
    return {"body": solid_id}


def handle_apply_safe_chamfer(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    if node.inputs and node.inputs[0].producer_node:
        input_handle_id = ctx.resolve_node_output(node.inputs[0].producer_node, node.inputs[0].output)
    else:
        input_handle_id = ctx.resolve_node_output(node.id, "body")
    body = ctx.object_store.get(input_handle_id)
    distance = float(node.params.get("distance_mm", 0))
    if distance > 0:
        try:
            body = body.chamfer(distance)
        except Exception:
            pass  # graceful degradation for chamfer

    solid_id = f"solid:{node.component}:{node.id}:body"
    handle = SolidHandle(id=solid_id, component_id=node.component, producer_node=node.id)
    ctx.object_store.put_solid(handle, body)
    ctx.bind_node_output(node.id, "body", solid_id)
    return {"body": solid_id}
