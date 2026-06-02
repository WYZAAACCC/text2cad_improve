"""SketchProfile CadQuery handlers — 2D sketch + extrude/cut operations.

v1.0: hardened — per-component state via object_store (not global dict),
      consistent handle ID format, proper chain continuity for all ops.
"""

from __future__ import annotations
import math
from seekflow_engineering_tools.generative_cad.runtime.handles import RuntimeHandle, SolidHandle


# ── Per-component state via object_store ─────────────────────────────────────

def _state_key(component_id: str, field: str) -> str:
    return f"__sketch_profile__{component_id}__{field}"


def _get_state(ctx, component_id: str, field: str, default=None):
    try:
        return ctx.object_store.get(_state_key(component_id, field))
    except KeyError:
        return default


def _set_state(ctx, component_id: str, field: str, value) -> None:
    ctx.object_store.put(
        RuntimeHandle(id=_state_key(component_id, field), type="profile"), value
    )


# ── Handlers ─────────────────────────────────────────────────────────────────

def handle_create_2d_sketch(node, ctx) -> dict:
    import cadquery as cq
    params = node.params
    plane = params.get("plane", "XY")
    ox = params.get("origin_x_mm", 0.0)
    oy = params.get("origin_y_mm", 0.0)
    wp = cq.Workplane(plane)
    if ox or oy:
        wp = wp.transformed(offset=(ox, oy, 0))
    cid = node.component
    _set_state(ctx, cid, "wp", wp)
    _set_state(ctx, cid, "last_point", None)
    _set_state(ctx, cid, "start_point", None)
    _set_state(ctx, cid, "closed", False)
    # Consistent handle ID: solid:{component}:{node_id}:{output_name}
    handle_id = f"sketch:{cid}:{node.id}:sketch"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
    return {"sketch": handle_id}


def handle_add_line_segment(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    cid = node.component
    start = params.get("start", {}); end = params.get("end", {})
    sx = float(start.get("x_mm", 0)); sy = float(start.get("y_mm", 0))
    ex = float(end.get("x_mm", 0)); ey = float(end.get("y_mm", 0))
    lp = _get_state(ctx, cid, "last_point")
    if lp: wp = wp.moveTo(lp[0], lp[1])
    else: wp = wp.moveTo(sx, sy)
    wp = wp.lineTo(ex, ey)
    _set_state(ctx, cid, "wp", wp)
    _set_state(ctx, cid, "last_point", (ex, ey))
    if _get_state(ctx, cid, "start_point") is None:
        _set_state(ctx, cid, "start_point", (sx, sy))
    handle_id = f"profile:{cid}:{node.id}:profile"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
    return {"profile": handle_id}


def handle_add_polyline(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    cid = node.component
    points = params.get("points", [])
    if len(points) < 2:
        raise ValueError("add_polyline requires at least 2 points")
    # Chain from last_point for continuity with previous segments
    lp = _get_state(ctx, cid, "last_point")
    if lp:
        wp = wp.moveTo(lp[0], lp[1])
        wp = wp.lineTo(float(points[0].get("x_mm", 0)), float(points[0].get("y_mm", 0)))
    else:
        wp = wp.moveTo(float(points[0].get("x_mm", 0)), float(points[0].get("y_mm", 0)))
    for pt in points[1:]:
        wp = wp.lineTo(float(pt.get("x_mm", 0)), float(pt.get("y_mm", 0)))
    last = points[-1]
    _set_state(ctx, cid, "wp", wp)
    _set_state(ctx, cid, "last_point", (float(last.get("x_mm", 0)), float(last.get("y_mm", 0))))
    if _get_state(ctx, cid, "start_point") is None:
        _set_state(ctx, cid, "start_point", (float(points[0].get("x_mm", 0)), float(points[0].get("y_mm", 0))))
    handle_id = f"profile:{cid}:{node.id}:profile"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
    return {"profile": handle_id}


def handle_add_arc_segment(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    cid = node.component
    start = params.get("start", {}); end = params.get("end", {}); center = params.get("center", {})
    direction = params.get("direction", "ccw")
    sx = float(start.get("x_mm", 0)); sy = float(start.get("y_mm", 0))
    ex = float(end.get("x_mm", 0)); ey = float(end.get("y_mm", 0))
    cx = float(center.get("x_mm", 0)); cy = float(center.get("y_mm", 0))
    lp = _get_state(ctx, cid, "last_point")
    if lp: wp = wp.moveTo(lp[0], lp[1])
    else: wp = wp.moveTo(sx, sy)
    radius = math.hypot(sx - cx, sy - cy)
    wp = wp.radiusArc((ex, ey), -radius if direction == "cw" else radius)
    _set_state(ctx, cid, "wp", wp)
    _set_state(ctx, cid, "last_point", (ex, ey))
    handle_id = f"profile:{cid}:{node.id}:profile"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
    return {"profile": handle_id}


def handle_add_circle(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    cid = node.component
    center = params.get("center", {})
    radius = float(params.get("radius_mm", 1))
    cx = float(center.get("x_mm", 0)); cy = float(center.get("y_mm", 0))
    wp = wp.moveTo(cx + radius, cy)
    wp = wp.radiusArc((cx - radius, cy), radius)
    wp = wp.radiusArc((cx + radius, cy), radius)
    _set_state(ctx, cid, "wp", wp)
    _set_state(ctx, cid, "last_point", (cx + radius, cy))
    handle_id = f"profile:{cid}:{node.id}:profile"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
    return {"profile": handle_id}


def handle_close_profile(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    wp = resolve_input_object(node, ctx, 0)
    cid = node.component
    sp = _get_state(ctx, cid, "start_point")
    if sp is None:
        ctx.warnings.append(f"close_profile on '{node.id}': no start_point, skipping close")
    else:
        wp = wp.close()
        _set_state(ctx, cid, "wp", wp)
    _set_state(ctx, cid, "closed", True)
    handle_id = f"profile:{cid}:{node.id}:profile"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
    return {"profile": handle_id}


def handle_extrude_profile(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    cid = node.component
    closed = _get_state(ctx, cid, "closed", False)
    if closed:
        wp = wp.close()
    depth = float(params.get("depth_mm", 1))
    direction = params.get("direction", "+")
    taper = float(params.get("taper_deg", 0))
    extrude_depth = depth if direction == "+" else -depth
    try:
        if abs(taper) > 0.01:
            solid = wp.taperedExtrude(extrude_depth, taper)
        else:
            solid = wp.extrude(extrude_depth)
    except Exception as e:
        raise RuntimeError(f"extrude_profile failed on '{node.id}': {e}")
    handle = SolidHandle(id=f"solid:{cid}:{node.id}:body", producer_node=node.id, component_id=cid)
    ctx.object_store.put_solid(handle, solid)
    return {"body": f"solid:{cid}:{node.id}:body"}


def handle_cut_profile(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    # input[0] = target solid, input[1] = profile to cut with
    target = resolve_input_object(node, ctx, 0)
    wp = resolve_input_object(node, ctx, 1)
    cid = node.component
    closed = _get_state(ctx, cid, "closed", False)
    if closed:
        wp = wp.close()
    depth = float(params.get("depth_mm", 1))
    direction = params.get("direction", "-")
    cut_depth = depth if direction == "+" else -depth
    try:
        result = target.cut(wp.extrude(cut_depth))
    except Exception as e:
        ctx.warnings.append(f"cut_profile failed on '{node.id}': {e}. Returning unmodified target.")
        result = target
    handle = SolidHandle(id=f"solid:{cid}:{node.id}:body", producer_node=node.id, component_id=cid)
    ctx.object_store.put_solid(handle, result)
    return {"body": f"solid:{cid}:{node.id}:body"}
