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
    key = _state_key(component_id, field)
    # Per-component state is updated in-place across multiple ops (e.g. add_polyline
    # updates 'wp' state set by create_2d_sketch). Use direct dict write to avoid
    # object_store.put() duplicate-ID rejection.
    ctx.object_store._objects[key] = value
    ctx.object_store._handles[key] = RuntimeHandle(id=key, type="profile")


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
    _set_state(ctx, cid, "sketch_plane", plane)
    _set_state(ctx, cid, "wp", wp)
    _set_state(ctx, cid, "last_point", None)
    _set_state(ctx, cid, "start_point", None)
    _set_state(ctx, cid, "closed", False)
    _set_state(ctx, cid, "polyline_points", [])
    # Consistent handle ID: solid:{component}:{node_id}:{output_name}
    handle_id = f"sketch:{cid}:{node.id}:sketch"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="sketch"), wp)
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
    # Accumulate polyline points for downstream operations (e.g. fillet_sketch)
    acc = _get_state(ctx, cid, "polyline_points", [])
    acc_points = [(float(p.get("x_mm", 0)), float(p.get("y_mm", 0))) for p in points]
    if not acc:
        # First polyline segment: keep all points including p0
        acc.extend(acc_points)
    else:
        # Bridge gap: insert first point of new segment as continuation
        acc.append(acc_points[0])
        acc.extend(acc_points[1:])
    _set_state(ctx, cid, "polyline_points", acc)
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
    r_start = math.hypot(sx - cx, sy - cy)
    r_end = math.hypot(ex - cx, ey - cy)
    if abs(r_start - r_end) > max(r_start, r_end) * 1e-3 + 0.01:
        msg = (
            f"add_arc_segment on '{node.id}': start→center ({r_start:.4f} mm) "
            f"≠ end→center ({r_end:.4f} mm) — center is not equidistant"
        )
        if getattr(node, "required", True):
            raise ValueError(msg)
        ctx.warnings.append(msg)
    radius = r_start
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
        try:
            wp = wp.close()
        except (ValueError, AttributeError):
            pass  # wire already closed (e.g. by mirror_profile or fillet_sketch)
        _set_state(ctx, cid, "wp", wp)
        # Verify the wire is actually closed — do NOT trust the catch-all pass above
        try:
            wires = wp.wires().vals()
            if len(wires) != 1:
                ctx.warnings.append(
                    f"close_profile on '{node.id}': expected 1 wire, got {len(wires)}"
                )
            elif not wires[0].IsClosed():
                if getattr(node, "required", True):
                    raise RuntimeError(
                        f"close_profile on '{node.id}': wire is not closed after close()"
                    )
                ctx.warnings.append(
                    f"close_profile on '{node.id}': wire is not closed — "
                    f"profile may produce invalid geometry"
                )
        except Exception:
            pass  # wire introspection failed, trust CadQuery close() result
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
    if not closed:
        wp = wp.close()
    depth = float(params.get("depth_mm", 1))
    direction = params.get("direction", "+")
    taper = float(params.get("taper_deg", 0))
    try:
        if direction == "both":
            # Symmetric extrude: CadQuery both=True uses depth as HALF-distance.
            # depth_mm=80 with "both" means total Z height = 80mm (±40mm from plane).
            solid = wp.extrude(depth / 2.0, both=True)
        elif abs(taper) > 0.01:
            extrude_depth = depth if direction == "+" else -depth
            solid = wp.taperedExtrude(extrude_depth, taper)
        else:
            extrude_depth = depth if direction == "+" else -depth
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
    if not closed:
        wp = wp.close()
    depth = float(params.get("depth_mm", 1))
    direction = params.get("direction", "-")
    cut_depth = depth if direction == "+" else -depth
    try:
        result = target.cut(wp.extrude(cut_depth))
    except Exception as e:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required cut_profile failed on '{node.id}': {e}"
            ) from e
        ctx.warnings.append(f"cut_profile failed on '{node.id}': {e}. Returning unmodified target.")
        result = target
    handle = SolidHandle(id=f"solid:{cid}:{node.id}:body", producer_node=node.id, component_id=cid)
    ctx.object_store.put_solid(handle, result)
    return {"body": f"solid:{cid}:{node.id}:body"}


def handle_revolve_profile(node, ctx) -> dict:
    """Revolve a closed 2D profile around the Z axis to create a rotationally symmetric solid.

    This is the key operation for building axisymmetric parts with varying radial thickness
    (e.g. turbine discs, wheels, pulleys) — the LLM draws an arbitrary R-Z closed polygon
    on the XZ plane and revolves it 360° to produce the solid.
    """
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    cid = node.component
    closed = _get_state(ctx, cid, "closed", False)
    if not closed:
        wp = wp.close()
    angle = float(params.get("angle_deg", 360.0))
    try:
        solid = wp.revolve(angle)
    except Exception as e:
        raise RuntimeError(f"revolve_profile failed on '{node.id}': {e}")
    handle = SolidHandle(id=f"solid:{cid}:{node.id}:body", producer_node=node.id, component_id=cid)
    ctx.object_store.put_solid(handle, solid)
    return {"body": f"solid:{cid}:{node.id}:body"}


def _compute_fillet_arc(prev_pt, corner_pt, next_pt, radius, centroid=None, num_segments=3):
    """Compute arc points that round a polyline corner.

    Returns list of (x,y) points forming the arc [tangent1, arc_1, ..., arc_n, tangent2],
    replacing the sharp corner at corner_pt.

    If radius is too large for the adjacent segments, returns [corner_pt] (no fillet).
    If adjacent segments are nearly collinear (angle ~ 180°), returns [corner_pt].
    Uses num_segments=3 — balances smoothness vs boolean-operation performance.

    The fillet center is chosen as the candidate (of the two chord-normal offsets)
    closer to `centroid` — i.e. on the polygon-interior side. The previous cross-
    product sign test picked the wrong side for some corners, making arcs bulge
    OUTSIDE the original profile bbox (e.g. disc Y ±38 bulged to ±41.57, inflating
    the revolved bbox Z from 76 to 83.14). Centroid selection keeps every arc
    inside the original convex hull.
    """
    import math
    dx1, dy1 = prev_pt[0] - corner_pt[0], prev_pt[1] - corner_pt[1]
    len1 = math.sqrt(dx1**2 + dy1**2)
    if len1 < 1e-9: return [corner_pt]
    dx1, dy1 = dx1/len1, dy1/len1
    dx2, dy2 = next_pt[0] - corner_pt[0], next_pt[1] - corner_pt[1]
    len2 = math.sqrt(dx2**2 + dy2**2)
    if len2 < 1e-9: return [corner_pt]
    dx2, dy2 = dx2/len2, dy2/len2
    cos_angle = dx1*dx2 + dy1*dy2
    if cos_angle > 0.95: return [corner_pt]  # nearly collinear, skip fillet
    half_angle = math.acos(max(-1, min(1, cos_angle))) / 2.0
    d = radius / math.tan(half_angle)
    if d >= len1 * 0.8 or d >= len2 * 0.8:
        return [corner_pt]  # radius too large relative to adjacent segments
    t1 = (corner_pt[0] + dx1 * d, corner_pt[1] + dy1 * d)
    t2 = (corner_pt[0] + dx2 * d, corner_pt[1] + dy2 * d)
    mx, my = (t1[0]+t2[0])/2, (t1[1]+t2[1])/2
    t2_vec = (t2[0]-t1[0], t2[1]-t1[1])
    t2_len = math.sqrt(t2_vec[0]**2 + t2_vec[1]**2)
    if t2_len < 1e-9: return [corner_pt]
    chord_nx = -t2_vec[1] / t2_len
    chord_ny = t2_vec[0] / t2_len
    h = math.sqrt(max(0, radius**2 - (t2_len/2)**2))
    # Two candidate centers straddle the chord; pick the one on the polygon-
    # interior side (closer to centroid) so the arc stays inside the profile.
    c1 = (mx + chord_nx * h, my + chord_ny * h)
    c2 = (mx - chord_nx * h, my - chord_ny * h)
    if centroid is not None:
        d1 = (c1[0] - centroid[0])**2 + (c1[1] - centroid[1])**2
        d2 = (c2[0] - centroid[0])**2 + (c2[1] - centroid[1])**2
        cx, cy = c1 if d1 < d2 else c2
    else:
        cross = dx1*dy2 - dy1*dx2
        cx, cy = c1 if cross < 0 else c2
    angle1 = math.atan2(t1[1]-cy, t1[0]-cx)
    angle2 = math.atan2(t2[1]-cy, t2[0]-cx)
    # Take the short arc from angle1 to angle2 (passes through the interior side).
    da = angle2 - angle1
    while da > math.pi: da -= 2*math.pi
    while da < -math.pi: da += 2*math.pi
    arc_pts = []
    for i in range(1, num_segments):
        a = angle1 + da * i / num_segments
        arc_pts.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
    return [t1] + arc_pts + [t2]


def _apply_fillets_to_polyline(points, radius, at_vertex_index=None):
    """Replace sharp corners in a closed polyline with radiused arc segments.

    ONLY the vertices listed in *at_vertex_index* are filleted.
    If *at_vertex_index* is None / empty / null, no filleting is performed
    — the LLM MUST explicitly select which vertices need rounding.

    Args:
        points: list of (x, y) tuples forming a closed loop
        radius: fillet radius in mm
        at_vertex_index: int → fillet only that vertex.
            list[int] → fillet only the listed vertices.
            None / [] → no filleting (identity pass).

    Returns:
        new list of (x, y) points with fillet arcs inserted
    """
    n = len(points)
    if n < 3: return list(points)

    # Normalise at_vertex_index to a set for O(1) lookup
    target_set: set[int] | None = None
    if isinstance(at_vertex_index, list) and len(at_vertex_index) > 0:
        target_set = set(at_vertex_index)
    elif isinstance(at_vertex_index, int):
        target_set = {at_vertex_index}

    # No explicit targets → no filleting (LLM must opt in)
    if target_set is None:
        return list(points)

    centroid = (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)
    result = []
    for i in range(n):
        prev = points[(i - 1) % n]
        curr = points[i]
        nxt = points[(i + 1) % n]

        if i not in target_set:
            result.append(curr)
            continue

        arc = _compute_fillet_arc(prev, curr, nxt, radius, centroid)
        result.extend(arc)
    return result


def handle_fillet_sketch(node, ctx) -> dict:
    """Apply 2D fillets using OCC native Wire.fillet2D().

    The LLM MUST specify at_vertex_index — a list of vertex indices to fillet.
    Uses OCC BRepFilletAPI_MakeFillet2d for correct arcs on convex AND reflex corners.
    """
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    cid = node.component
    radius = float(params.get("radius_mm", 0.5))
    at_index = params.get("at_vertex_index")

    # ── Parse target vertices ──
    target_indices: set[int] = set()
    if isinstance(at_index, list):
        target_indices = set(at_index)
    elif isinstance(at_index, int):
        target_indices = {at_index}

    closed = _get_state(ctx, cid, "closed", False)
    plane = _get_state(ctx, cid, "sketch_plane", "XY")

    if not target_indices:
        msg = (
            f"fillet_sketch on '{node.id}': at_vertex_index empty — "
            f"no filleting applied (must specify explicit vertex indices)"
        )
        if getattr(node, "required", True):
            raise RuntimeError(msg)
        ctx.warnings.append(msg)
    else:
        try:
            # Ensure wire is closed before filleting
            if not closed:
                wp = wp.close()
                _set_state(ctx, cid, "closed", True)
                closed = True

            wires = wp.wires().vals()
            if not wires:
                raise RuntimeError("no wire found in workplane")
            if len(wires) > 1:
                ctx.warnings.append(
                    f"fillet_sketch on '{node.id}': {len(wires)} wires found, "
                    f"using wires[0] — vertex indices may not be reliable"
                )

            wire = wires[0]
            all_verts = wire.Vertices()
            n_verts = len(all_verts)

            # Select OCC Vertex objects at the requested indices
            selected = []
            for idx in sorted(target_indices):
                if 0 <= idx < n_verts:
                    selected.append(all_verts[idx])
                else:
                    ctx.warnings.append(
                        f"fillet_sketch on '{node.id}': index {idx} out of "
                        f"range (wire has {n_verts} vertices), skipping"
                    )

            if selected:
                import cadquery as cq
                # OCC native 2D fillet
                filleted_wire = wire.fillet2D(radius, selected)

                # Place the filleted wire directly into a new workplane.
                # This preserves CIRCLE edges as true arcs (no polyline approx).
                wp = cq.Workplane(plane)
                wp.ctx.pendingWires = [filleted_wire]
                _set_state(ctx, cid, "closed", True)

                ctx.operation_metrics.append({
                    "node_id": node.id, "op": "fillet_sketch",
                    "radius_mm": radius, "n_vertices_selected": len(selected),
                    "engine": "OCC_fillet2D",
                })
        except Exception as e:
            if getattr(node, "required", True):
                raise RuntimeError(
                    f"required fillet_sketch failed on '{node.id}': {e}"
                ) from e
            ctx.warnings.append(
                f"fillet_sketch on '{node.id}': OCC fillet2D failed ({e}), "
                f"keeping original profile"
            )

    handle_id = f"profile:{cid}:{node.id}:profile"
    ctx.object_store._objects[handle_id] = wp
    ctx.object_store._handles[handle_id] = RuntimeHandle(id=handle_id, type="profile")
    return {"profile": handle_id}


def handle_fillet_sketch_v2(node, ctx) -> dict:
    """Semantic fillet_sketch@2.0.0 — stable corner identification via edge adjacency.

    Uses ProfileGraph (built from polyline_points state) to resolve
    corner_id + between_segments → vertex, then applies OCC fillet2D
    with feasibility pre-check and postcondition verification.
    """
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    from seekflow_engineering_tools.generative_cad.dialects.sketch_profile.profile_graph import (
        ProfileGraph,
    )
    from seekflow_engineering_tools.generative_cad.dialects.sketch_profile.fillet_solver import (
        check_fillet_feasibility,
    )
    from seekflow_engineering_tools.generative_cad.dialects.sketch_profile.postconditions import (
        check_closed, check_wire_count, check_fillet_arc_count,
    )

    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    cid = node.component
    wire_id = params.get("wire_id", "profile")
    targets = params.get("targets", [])
    strict = params.get("strict", True)

    def _fail_or_warn(msg: str):
        """Raise if node is required, else warn and return original profile."""
        if getattr(node, "required", True):
            raise RuntimeError(f"fillet_sketch@2 on '{node.id}': {msg}")
        ctx.warnings.append(f"fillet_sketch@2 on '{node.id}': {msg}")
        return _return_profile(ctx, cid, node)

    if not targets:
        msg = f"fillet_sketch@2 on '{node.id}': no targets specified"
        if getattr(node, "required", True):
            raise RuntimeError(msg)
        ctx.warnings.append(msg)
        return _return_profile(ctx, cid, node)

    closed = _get_state(ctx, cid, "closed", False)
    plane = _get_state(ctx, cid, "sketch_plane", "XY")

    # ── Build ProfileGraph from stored polyline points ──
    points = _get_state(ctx, cid, "polyline_points", [])
    if len(points) < 3:
        return _fail_or_warn(
            f"polyline_points has {len(points)} points (need ≥3 to build ProfileGraph)"
        )
    graph = ProfileGraph.from_polyline(points, wire_id=wire_id)

    # ── Feasibility pre-check ──
    feasibility = check_fillet_feasibility(graph, wire_id, targets)
    if not feasibility.all_feasible:
        infeasible_detail = [
            {"corner_id": t.corner_id, "error_code": t.error_code,
             "edge_id": t.edge_id, "available_mm": t.edge_length_mm,
             "required_mm": t.required_length_mm,
             "suggested_max_radius_mm": t.suggested_max_radius_mm}
            for t in feasibility.infeasible
        ]
        msg = (
            f"fillet_sketch@2 on '{node.id}': {len(feasibility.infeasible)} "
            f"target(s) infeasible — {infeasible_detail}"
        )
        if strict or getattr(node, "required", True):
            raise RuntimeError(msg)
        ctx.warnings.append(msg)
        if len(feasibility.infeasible) == len(targets):
            # All targets failed → return original profile
            return _return_profile(ctx, cid, node)

    # ── Ensure wire is closed ──
    if not closed:
        wp = wp.close()
        _set_state(ctx, cid, "closed", True)
        closed = True

    wires = wp.wires().vals()
    wc = check_wire_count(wires, 1)
    if not wc.passed:
        return _fail_or_warn(wc.message)

    wire = wires[0]
    all_verts = wire.Vertices()
    n_before = len(all_verts)

    # ── Resolve semantic corners → OCC vertices ──
    selected: list = []
    for t in targets:
        try:
            corner_vid = graph.find_corner_vertex(
                t["between_segments"][0], t["between_segments"][1], wire_id,
            )
        except (ValueError, KeyError) as exc:
            if getattr(node, "required", True) and (strict or t.get("required", True)):
                raise RuntimeError(
                    f"fillet_sketch@2 on '{node.id}': "
                    f"corner '{t['corner_id']}' not found — {exc}"
                ) from exc
            ctx.warnings.append(
                f"fillet_sketch@2 on '{node.id}': skipping corner "
                f"'{t['corner_id']}' — {exc}"
            )
            continue

        # Map vertex_id to nearest OCC vertex (same polyline → same topology).
        # OCC wire reconstruction may shift coordinates slightly (floating-point),
        # so we always pick the closest vertex without a hard distance cutoff.
        v = graph.vertices[corner_vid]
        best_idx, best_dist = -1, float("inf")
        for idx, occ_v in enumerate(all_verts):
            p = occ_v.toTuple()
            d = (p[0] - v.x_mm) ** 2 + (p[1] - v.y_mm) ** 2
            if d < best_dist:
                best_dist, best_idx = d, idx
        if best_idx >= 0:
            selected.append(all_verts[best_idx])
            if best_dist > 1e-2:
                ctx.warnings.append(
                    f"fillet_sketch@2 on '{node.id}': corner '{t['corner_id']}' "
                    f"matched at distance {best_dist:.4f} mm² — OCC may have "
                    f"shifted vertex position slightly"
                )
        else:
            msg = (
                f"fillet_sketch@2 on '{node.id}': corner '{t['corner_id']}' "
                f"(vertex {corner_vid}) — OCC wire has no vertices"
            )
            if getattr(node, "required", True) and (strict or t.get("required", True)):
                raise RuntimeError(msg)
            ctx.warnings.append(msg)

    if not selected:
        msg = f"fillet_sketch@2 on '{node.id}': no corners mapped to OCC vertices"
        if getattr(node, "required", True):
            raise RuntimeError(msg)
        ctx.warnings.append(msg)
        return _return_profile(ctx, cid, node)

    # ── Apply filleting ──
    try:
        import cadquery as cq
        first_radius = targets[0]["radius_mm"]
        filleted_wire = wire.fillet2D(first_radius, selected)
        wp = cq.Workplane(plane)
        wp.ctx.pendingWires = [filleted_wire]
        _set_state(ctx, cid, "closed", True)

        # Postcondition: vertex count increased
        new_verts = filleted_wire.Vertices()
        arc_check = check_fillet_arc_count(n_before, len(new_verts), len(selected))
        closed_check = check_closed(filleted_wire)
        for check in (arc_check, closed_check):
            if not check.passed:
                ctx.warnings.append(
                    f"fillet_sketch@2 on '{node.id}': {check.code} — {check.message}"
                )

        ctx.operation_metrics.append({
            "node_id": node.id, "op": "fillet_sketch@2",
            "runtime_version": "2.0.0",
            "n_targets": len(targets),
            "n_selected": len(selected),
            "n_verts_before": n_before,
            "n_verts_after": len(new_verts),
            "feasibility": "ok" if feasibility.all_feasible else "partial",
            "engine": "OCC_fillet2D+precheck",
        })

    except Exception as exc:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required fillet_sketch@2 failed on '{node.id}': {exc}"
            ) from exc
        ctx.warnings.append(
            f"fillet_sketch@2 on '{node.id}': OCC fillet2D failed ({exc}), "
            f"keeping original profile"
        )
        return _return_profile(ctx, cid, node)

    return _return_profile(ctx, cid, node)


def _return_profile(ctx, cid: str, node) -> dict:
    """Return the current profile handle for the component."""
    handle_id = f"profile:{cid}:{node.id}:profile"
    ctx.object_store._objects[handle_id] = _get_state(ctx, cid, "wp")
    ctx.object_store._handles[handle_id] = RuntimeHandle(id=handle_id, type="profile")
    return {"profile": handle_id}


def handle_mirror_profile(node, ctx) -> dict:
    """Mirror the sketch profile and union with the original.

    Useful for symmetric profiles like fir-tree slots: draw one half, mirror to get the full shape.
    """
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    cid = node.component
    axis = params.get("axis", "X")
    closed = _get_state(ctx, cid, "closed", False)
    if not closed:
        wp = wp.close()
    try:
        # CadQuery 2.7 mirror(str) is broken for single-axis strings.
        # Use mirrorX() / mirrorY() which work correctly.
        if axis == "X":
            wp = wp.mirrorX()
        elif axis == "Y":
            wp = wp.mirrorY()
        else:
            wp = wp.mirror(axis, union=True)
    except Exception as e:
        if getattr(node, "required", True):
            raise RuntimeError(f"mirror_profile failed on '{node.id}': {e}")
        ctx.warnings.append(f"mirror_profile failed on '{node.id}': {e}")
    _set_state(ctx, cid, "wp", wp)
    _set_state(ctx, cid, "closed", True)
    handle_id = f"profile:{cid}:{node.id}:profile"
    ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
    return {"profile": handle_id}
