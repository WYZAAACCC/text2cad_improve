"""SketchProfile CadQuery handlers — 2D sketch + extrude/cut operations.

Each handler stores its output (a CadQuery Workplane or solid) in the
object_store under its output handle ID. Downstream nodes resolve inputs
via resolve_input_object() to get the actual CadQuery objects.
Handlers also store private state keys (last_point, start_point, closed)
in a shared dict keyed by component ID.
"""

from __future__ import annotations
import math
from seekflow_engineering_tools.generative_cad.runtime.handles import RuntimeHandle, SolidHandle

# Per-component state for sketch accumulation
_STATE: dict[str, dict] = {}


def _cstate(component_id: str) -> dict:
    if component_id not in _STATE:
        _STATE[component_id] = {}
    return _STATE[component_id]


def handle_create_2d_sketch(node, ctx) -> dict:
    import cadquery as cq
    params = node.params
    plane = params.get("plane", "XY")
    ox = params.get("origin_x_mm", 0.0)
    oy = params.get("origin_y_mm", 0.0)
    wp = cq.Workplane(plane)
    if ox or oy:
        wp = wp.transformed(offset=(ox, oy, 0))
    st = _cstate(node.component)
    st["wp"] = wp
    st["last_point"] = None
    st["start_point"] = None
    st["closed"] = False
    # Store workplane under output handle so downstream can resolve it
    handle_id = f"sketch:{node.id}"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="sketch"), wp)
    return {"sketch": handle_id}


def handle_add_line_segment(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    start = params["start"]; end = params["end"]
    sx, sy = start["x_mm"], start["y_mm"]
    ex, ey = end["x_mm"], end["y_mm"]
    st = _cstate(node.component)
    lp = st.get("last_point")
    if lp: wp = wp.moveTo(lp[0], lp[1])
    else: wp = wp.moveTo(sx, sy)
    wp = wp.lineTo(ex, ey)
    st["wp"] = wp
    st["last_point"] = (ex, ey)
    if st.get("start_point") is None:
        st["start_point"] = (sx, sy)
    handle_id = f"profile:{node.id}"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
    return {"profile": handle_id}


def handle_add_polyline(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    points = params["points"]
    first = points[0]
    wp = wp.moveTo(first["x_mm"], first["y_mm"])
    for pt in points[1:]:
        wp = wp.lineTo(pt["x_mm"], pt["y_mm"])
    last = points[-1]
    st = _cstate(node.component)
    st["wp"] = wp
    st["last_point"] = (last["x_mm"], last["y_mm"])
    st["start_point"] = (first["x_mm"], first["y_mm"])
    handle_id = f"profile:{node.id}"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
    return {"profile": handle_id}


def handle_add_arc_segment(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    start = params["start"]; end = params["end"]; center = params["center"]
    direction = params.get("direction", "ccw")
    sx, sy = start["x_mm"], start["y_mm"]
    ex, ey = end["x_mm"], end["y_mm"]
    cx, cy = center["x_mm"], center["y_mm"]
    st = _cstate(node.component)
    lp = st.get("last_point")
    if lp: wp = wp.moveTo(lp[0], lp[1])
    else: wp = wp.moveTo(sx, sy)
    radius = math.hypot(sx - cx, sy - cy)
    wp = wp.radiusArc((ex, ey), radius * -1 if direction == "cw" else radius)
    st["wp"] = wp
    st["last_point"] = (ex, ey)
    handle_id = f"profile:{node.id}"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
    return {"profile": handle_id}


def handle_add_circle(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    center = params["center"]; radius = params["radius_mm"]
    cx, cy = center["x_mm"], center["y_mm"]
    wp = wp.moveTo(cx + radius, cy)
    wp = wp.radiusArc((cx - radius, cy), radius)
    wp = wp.radiusArc((cx + radius, cy), radius)
    st = _cstate(node.component)
    st["wp"] = wp
    st["last_point"] = (cx + radius, cy)
    handle_id = f"profile:{node.id}"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
    return {"profile": handle_id}


def handle_close_profile(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    wp = resolve_input_object(node, ctx, 0)
    st = _cstate(node.component)
    sp = st.get("start_point")
    if sp: wp = wp.close()
    st["wp"] = wp
    st["closed"] = True
    handle_id = f"profile:{node.id}"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
    return {"profile": handle_id}


def handle_extrude_profile(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    st = _cstate(node.component)
    if st.get("closed"): wp = wp.close()
    depth = params["depth_mm"]
    direction = params.get("direction", "+")
    taper = params.get("taper_deg", 0.0)
    extrude_depth = depth if direction == "+" else -depth
    if abs(taper) > 0.01:
        solid = wp.taperedExtrude(extrude_depth, taper)
    else:
        solid = wp.extrude(extrude_depth)
    handle = SolidHandle(id=f"solid:{node.id}", producer_node=node.id, component_id=node.component)
    ctx.object_store.put_solid(handle, solid)
    return {"body": f"solid:{node.id}"}


def handle_cut_profile(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 1)  # index 1 = profile
    target = resolve_input_object(node, ctx, 0)  # index 0 = solid to cut
    st = _cstate(node.component)
    if st.get("closed"): wp = wp.close()
    depth = params["depth_mm"]
    direction = params.get("direction", "-")
    cut_depth = depth if direction == "+" else -depth
    result = target.cut(wp.extrude(cut_depth))
    handle = SolidHandle(id=f"solid:{node.id}", producer_node=node.id, component_id=node.component)
    ctx.object_store.put_solid(handle, result)
    return {"body": f"solid:{node.id}"}
