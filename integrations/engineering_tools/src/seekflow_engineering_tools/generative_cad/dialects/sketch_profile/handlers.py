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
    return ctx.get_component_state(component_id, field, default)


def _set_state(ctx, component_id: str, field: str, value) -> None:
    ctx.set_component_state(component_id, field, value)


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
        if getattr(node, "required", True):
            raise RuntimeError(f"close_profile on '{node.id}': no start_point")
        ctx.warnings.append(f"close_profile on '{node.id}': no start_point, skipping close")
        handle_id = f"profile:{cid}:{node.id}:profile"
        ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
        return {"profile": handle_id}
    wp = wp.close()
    # Verify closure produced exactly one wire
    wires = wp.wires().vals()
    if len(wires) != 1:
        raise RuntimeError(f"close_profile on '{node.id}': expected 1 wire, got {len(wires)}")
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
    depth = float(params.get("depth_mm", 1))
    direction = params.get("direction", "+")
    taper = float(params.get("taper_deg", 0))
    try:
        if direction == "both":
            half = depth / 2.0
            if abs(taper) > 0.01:
                solid = wp.taperedExtrude(half, taper, both=True)
            else:
                solid = wp.extrude(half, both=True)
        else:
            extrude_depth = depth if direction == "+" else -depth
            if abs(taper) > 0.01:
                solid = wp.taperedExtrude(extrude_depth, taper)
            else:
                solid = wp.extrude(extrude_depth)
    except Exception as e:
        raise RuntimeError(f"extrude_profile failed on '{node.id}': {e}")
    handle = SolidHandle(id=f"solid:{cid}:{node.id}:body", producer_node=node.id, component_id=cid)
    ctx.object_store.put_solid(handle, solid)

    # ── Phase 5: Produce topology delta for extrude faces ──
    _try_produce_extrude_profile_topology(node=node, ctx=ctx, solid=solid)

    return {"body": f"solid:{cid}:{node.id}:body"}


def handle_revolve_profile(node, ctx) -> dict:
    """Revolve a closed 2D profile around Z axis using OCCT BRepPrimAPI_MakeRevol.

    CadQuery native revolve has a known limitation with XZ-plane profiles
    (produces flat/degenerate geometry). OCCT BRepPrimAPI_MakeRevol reliably
    handles axisymmetric profiles in any plane.
    """
    import cadquery as cq
    import math
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
    from OCP.gp import gp_Ax1, gp_Pnt, gp_Dir
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.ShapeFix import ShapeFix_Shape
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle

    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    cid = node.component
    angle = float(params.get("angle_deg", 360))

    # Extract wire and build face
    wire = wp.wire().val()
    face = BRepBuilderAPI_MakeFace(wire.wrapped, False).Face()

    # Revolve around Z axis
    z_axis = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
    rev_angle = angle * math.pi / 180.0
    revol = BRepPrimAPI_MakeRevol(face, z_axis, rev_angle)
    revol.Build()
    if not revol.IsDone():
        raise RuntimeError("BRepPrimAPI_MakeRevol failed")

    shape = revol.Shape()
    # Fix minor BRep issues that OCCT MakeRevol sometimes produces
    fixer = ShapeFix_Shape(shape)
    fixer.Perform()
    shape = fixer.Shape()
    cad_solid = cq.Shape.cast(shape)
    # Wrap as Workplane (standard CadQuery convention for solid handles)
    solid_wp = cq.Workplane("XY").newObject([cad_solid])

    handle = SolidHandle(id=f"solid:{cid}:{node.id}:body", producer_node=node.id, component_id=cid)
    ctx.object_store.put_solid(handle, solid_wp)

    # ── Phase 5: Produce topology delta for revolve faces ──
    _try_produce_revolve_profile_topology(
        node=node, ctx=ctx, solid=solid_wp,
        angle_deg=angle, axis="Z",
    )

    return {"body": f"solid:{cid}:{node.id}:body"}


def _try_produce_extrude_profile_topology(
    *, node, ctx, solid,
) -> None:
    """Phase 5: Build topology delta for sketch_profile extrude faces."""
    try:
        from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
            build_entity_records_from_delta, name_extrude_faces,
        )
    except ImportError:
        return
    try:
        doc_id = getattr(node, "component", "unknown") or "unknown"
        delta = name_extrude_faces(
            solid, document_id=doc_id,
            component_id=node.component or "unknown",
            producer_node_id=node.id,
            extrude_plane="XY", direction="+",
        )
        records = build_entity_records_from_delta(delta, document_id=doc_id)
        for rec in records:
            ctx.topology_registry.register_entity(rec)
        ctx.topology_registry.apply_delta(delta)
        ctx.topology_events.append({
            "event": "extrude_profile_topology_produced",
            "node_id": node.id, "face_count": len(delta.relations),
        })
    except Exception as exc:
        ctx.topology_warnings.append({
            "node_id": node.id, "phase": "extrude_profile_topology", "error": str(exc),
        })


def _try_produce_revolve_profile_topology(
    *, node, ctx, solid,
    angle_deg: float = 360.0, axis: str = "Z",
) -> None:
    """Phase 5: Build topology delta for sketch_profile revolve faces."""
    try:
        from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
            build_entity_records_from_delta, name_revolve_faces,
        )
    except ImportError:
        return
    try:
        doc_id = getattr(node, "component", "unknown") or "unknown"
        delta = name_revolve_faces(
            solid, document_id=doc_id,
            component_id=node.component or "unknown",
            producer_node_id=node.id,
            angle_deg=angle_deg, axis=axis,
        )
        records = build_entity_records_from_delta(delta, document_id=doc_id)
        for rec in records:
            ctx.topology_registry.register_entity(rec)
        ctx.topology_registry.apply_delta(delta)
        ctx.topology_events.append({
            "event": "revolve_profile_topology_produced",
            "node_id": node.id, "face_count": len(delta.relations),
        })
    except Exception as exc:
        ctx.topology_warnings.append({
            "node_id": node.id, "phase": "revolve_profile_topology", "error": str(exc),
        })


def handle_fillet_sketch(node, ctx) -> dict:
    """Apply 2D fillets to profile wire vertices using deferred batch strategy.

    The LLM chains multiple fillet_sketch calls per component (one per vertex).
    Applying them sequentially causes chain-failure because each call modifies
    the wire and creates arc vertices that conflict with subsequent fillets.

    Fix: cache the original wire on first call. Accumulate target indices.
    Each call re-applies ALL accumulated targets to the ORIGINAL wire in a
    single fillet2D() call. This lets OCC resolve all fillets simultaneously.
    """
    import cadquery as cq
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    from seekflow_engineering_tools.generative_cad.runtime.handles import RuntimeHandle

    params = node.params
    wp = resolve_input_object(node, ctx, 0)
    cid = node.component
    radius = float(params.get("radius_mm", 1))
    vertex_idx = params.get("at_vertex_index", None)

    try:
        wires = wp.wires().vals()
        if not wires:
            ctx.warnings.append(f"fillet_sketch on '{node.id}': no wires, passing through")
            handle_id = f"profile:{cid}:{node.id}:profile"
            ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
            return {"profile": handle_id}

        wire = wires[0]
        vertices = list(wire.Vertices())
        n_verts = len(vertices)

        if n_verts < 3:
            ctx.warnings.append(f"fillet_sketch on '{node.id}': <3 vertices, passing through")
            handle_id = f"profile:{cid}:{node.id}:profile"
            ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
            return {"profile": handle_id}

        # Determine target vertices
        if isinstance(vertex_idx, list):
            # Multi-radius list form: use position-based lookup for chain safety.
            # Cache original vertex positions on first call, then match by proximity.
            orig_key = "__fillet_orig_pos__"
            orig_pos = _get_state(ctx, cid, orig_key)
            if orig_pos is None:
                orig_pos = [(v.Center().x, v.Center().y) for v in vertices]
                _set_state(ctx, cid, orig_key, orig_pos)
            # Find target vertices in current wire by matching original positions
            targets = []
            for vi in vertex_idx:
                vi_int = int(vi)
                if 0 <= vi_int < len(orig_pos):
                    ox, oy = orig_pos[vi_int]
                    best_v, best_d = None, float('inf')
                    for v in vertices:
                        c = v.Center()
                        d = (c.x - ox)**2 + (c.y - oy)**2
                        if d < best_d:
                            best_d, best_v = d, v
                    if best_v is not None:
                        targets.append(best_v)
            # Apply directly to current wire (not accumulator — each group has different radius)
            filleted_wire = wire.fillet2D(radius, targets)
            ref_plane = wp.plane
        elif vertex_idx is not None:
            # Single vertex — use accumulator pattern for chain safety
            acc_key = "__fillet_acc__"
            acc = _get_state(ctx, cid, acc_key)
            if acc is None:
                acc = {"orig_wire": wire, "plane": wp.plane, "radius": None, "indices": set(), "all": False}
                _set_state(ctx, cid, acc_key, acc)

            if acc["radius"] is None:
                acc["radius"] = radius

            vi = int(vertex_idx)
            if vi < n_verts:
                acc["indices"].add(vi)

            orig_verts = list(acc["orig_wire"].Vertices())
            orig_n = len(orig_verts)
            targets = [orig_verts[i] for i in sorted(acc["indices"]) if i < orig_n]
        else:
            # None = fillet all vertices
            targets = vertices

        if not targets:
            handle_id = f"profile:{cid}:{node.id}:profile"
            ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
            return {"profile": handle_id}

        if isinstance(vertex_idx, list):
            # Already applied at lines 290-291; just update workplane
            ref_plane = wp.plane
        else:
            # Accumulator form: re-apply all fillets to original wire
            filleted_wire = acc["orig_wire"].fillet2D(acc["radius"], targets)
            ref_plane = acc["plane"]

        # Update workplane
        new_wp = cq.Workplane(ref_plane, obj=filleted_wire).toPending()
        _set_state(ctx, cid, "wp", new_wp)
        handle_id = f"profile:{cid}:{node.id}:profile"
        ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), new_wp)
        return {"profile": handle_id}

    except Exception as e:
        if getattr(node, "required", True) and node.degradation_policy == "fail":
            # §6.1 头号可修类别: fillet 半径超局部几何 — 带节点归因的 typed
            # exception, 使 runtime repair 分类器可证因果 (消息与旧行为一致)
            from seekflow_engineering_tools.generative_cad.runtime.diagnostics import (
                RuntimeIssue,
            )
            from seekflow_engineering_tools.generative_cad.runtime.errors import (
                GcadRuntimeError,
            )
            raise GcadRuntimeError(RuntimeIssue(
                stage="operation_execution",
                code="FILLET_SKETCH_FAILED",
                message=f"fillet_sketch failed on '{node.id}': {e}",
                node_id=node.id,
                component_id=getattr(node, "component", None),
                dialect=getattr(node, "dialect", None),
                operation=node.op,
                operation_version=getattr(node, "op_version", None),
                exception_type=type(e).__name__,
                repairability="repairable",
                suggested_paths=[f"/nodes/{node.id}/params"],
                evidence={"error_detail": str(e)},
            )) from e
        ctx.warnings.append(f"fillet_sketch failed on '{node.id}': {e}. Passing through.")
        handle_id = f"profile:{cid}:{node.id}:profile"
        ctx.object_store.put(RuntimeHandle(id=handle_id, type="profile"), wp)
        return {"profile": handle_id}


def handle_cut_profile(node, ctx) -> dict:
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    params = node.params
    # input[0] = target solid, input[1] = profile to cut with
    target = resolve_input_object(node, ctx, 0)
    wp = resolve_input_object(node, ctx, 1)
    cid = node.component
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
