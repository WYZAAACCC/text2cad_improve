"""LoftSweep CadQuery handlers — sweep, loft, helix."""
from __future__ import annotations
import math
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle


def _store_solid(node, ctx, obj) -> str:
    sid = f"solid:{node.component}:{node.id}:body"
    ctx.object_store.put_solid(SolidHandle(id=sid, component_id=node.component, producer_node=node.id), obj)
    ctx.bind_node_output(node.id, "body", sid)
    return sid


def _degrade(node, ctx, body, op_name: str) -> str:
    ctx.warnings.append(f"'{op_name}' skipped on '{node.id}': operation failed. Part may be incomplete.")
    return _store_solid(node, ctx, body)


# ═══════════════════════════════════════════════════════════════════════════════

def handle_create_sweep_path(node, ctx) -> dict:
    """Create a 3D path from points for subsequent sweep operations."""
    points = node.params.get("path_points", [])
    if len(points) < 2:
        raise ValueError("Need at least 2 path points")
    cid = node.component
    from seekflow_engineering_tools.generative_cad.runtime.handles import RuntimeHandle
    ctx.object_store.put(
        RuntimeHandle(id=f"curve:{cid}:{node.id}:curve", type="curve", component_id=cid, producer_node=node.id),
        points,
    )
    return {"curve": f"curve:{cid}:{node.id}:curve"}


def handle_sweep_profile(node, ctx) -> dict:
    """Sweep a 2D profile along a previously defined path."""
    import cadquery as cq
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object

    # input[0] = path (list of Point3D), input[1] = optional solid to merge into
    path_data = resolve_input_object(node, ctx, 0)

    params = node.params
    shape = params.get("shape", "circle")
    radius = float(params.get("radius_mm", 5))
    width = float(params.get("width_mm", 10))
    height = float(params.get("height_mm", 10))

    # Convert path point dicts to CadQuery vectors
    pts = []
    for p in path_data:
        x = float(p.get("x_mm", p.get("x", 0))) if isinstance(p, dict) else float(p[0])
        y = float(p.get("y_mm", p.get("y", 0))) if isinstance(p, dict) else float(p[1])
        z = float(p.get("z_mm", p.get("z", 0))) if isinstance(p, dict) else float(p[2])
        pts.append(cq.Vector(x, y, z))

    if len(pts) < 2:
        raise ValueError("Need at least 2 path points for sweep")

    try:
        # Build path as NURBS spline (G1 continuous, not polyline)
        if len(pts) == 2:
            path_wire = cq.Workplane("XY").moveTo(pts[0].x, pts[0].y).lineTo(pts[1].x, pts[1].y)
        else:
            # Use spline for 3+ points — smooth G1 continuous path
            path_wire = cq.Workplane("XY").spline(pts)

        # Self-intersection check: sweep path must not cross itself
        # Simple heuristic: check if any two non-adjacent segments come within 0.1mm
        for i in range(len(pts) - 2):
            for j in range(i + 2, len(pts) - 1):
                d = (pts[i] - pts[j]).Length
                if d < 0.1:
                    raise RuntimeError(
                        f"Sweep path self-intersects: points {i} and {j} are {d:.4f}mm apart"
                    )

        # Build profile
        if shape == "circle":
            profile = cq.Workplane("XZ").circle(radius)
        else:
            profile = cq.Workplane("XZ").rect(width, height)

        # Sweep
        solid = profile.sweep(path_wire)
    except Exception as e:
        raise RuntimeError(f"sweep_profile failed on '{node.id}': {e}")

    return {"body": _store_solid(node, ctx, solid)}


def handle_loft_sections(node, ctx) -> dict:
    """Loft between multiple cross-sections at different 3D positions."""
    import cadquery as cq

    sections = node.params.get("sections", [])
    if len(sections) < 2:
        raise ValueError("Need at least 2 sections for loft")

    try:
        wires = []
        for i, sec in enumerate(sections):
            pos = sec.get("position", {})
            x = float(pos.get("x_mm", 0))
            y = float(pos.get("y_mm", 0))
            z = float(pos.get("z_mm", 0))
            shape = sec.get("shape", "circle")
            wp = cq.Workplane("XY").workplane(offset=z).center(x, y)
            if shape == "circle":
                r = float(sec.get("radius_mm", 10))
                wires.append(wp.circle(r))
            elif shape == "rectangle":
                w = float(sec.get("width_mm", 20))
                h = float(sec.get("height_mm", 20))
                wires.append(wp.rect(w, h))
            elif shape == "ellipse":
                w = float(sec.get("width_mm", 20))
                h = float(sec.get("height_mm", 20))
                wires.append(wp.ellipse(w / 2.0, h / 2.0))

        ruled = node.params.get("ruled", False)
        continuity = node.params.get("continuity", "G0")
        solid = cq.Workplane("XY").add(wires).toPending().loft(ruled=ruled)
        # Note: G1/G2 loft requires CadQuery/OCCT 7.7+ with BRepOffsetAPI_ThruSections.
        # For now, G0 (default) is always used. The continuity parameter is recorded
        # for future OCCT versions that support it.
        if continuity in ("G1", "G2"):
            ctx.warnings.append(
                f"loft_sections on '{node.id}': continuity={continuity} requested. "
                f"Current CadQuery/OCCT only supports G0 (tangent) loft. "
                f"Result is G0 continuous."
            )
    except Exception as e:
        raise RuntimeError(f"loft_sections failed on '{node.id}': {e}")

    return {"body": _store_solid(node, ctx, solid)}


def handle_helix_sweep(node, ctx) -> dict:
    """Sweep a profile along a helical path (spring/thread)."""
    import cadquery as cq

    params = node.params
    radius = float(params.get("radius_mm", 10))
    height = float(params.get("height_mm", 50))
    pitch = float(params.get("pitch_mm", 5))
    profile_r = float(params.get("profile_radius_mm", 2))
    variable = params.get("variable_pitch", False)

    try:
        # Curvature safety check: profile must fit within the helix curvature
        min_curvature_radius = pitch / (2 * math.pi)
        if profile_r > min_curvature_radius * 0.8:
            ctx.warnings.append(
                f"helix_sweep on '{node.id}': profile radius ({profile_r:.1f}mm) > "
                f"80% of minimum curvature radius ({min_curvature_radius:.1f}mm). "
                f"Helix may self-intersect — consider reducing profile_radius_mm "
                f"or increasing pitch_mm."
            )

        if variable:
            start_p = float(params.get("start_pitch_mm", pitch))
            end_p = float(params.get("end_pitch_mm", pitch * 2))
            helix = cq.Workplane("XY").parametricCurve(
                lambda t: (
                    radius * math.cos(2 * math.pi * t),
                    radius * math.sin(2 * math.pi * t),
                    (start_p + (end_p - start_p) * t / 5.0) * t,
                ),
                N=200,
            )
        else:
            # Constant pitch helix
            wire = cq.Workplane("XY").parametricCurve(
                lambda t: (
                    radius * math.cos(2 * math.pi * t),
                    radius * math.sin(2 * math.pi * t),
                    pitch * t,
                ),
                N=200,
            )
            helix = wire

        profile = cq.Workplane("XZ").circle(profile_r)
        solid = profile.sweep(helix)
    except Exception as e:
        raise RuntimeError(f"helix_sweep failed on '{node.id}': {e}")

    return {"body": _store_solid(node, ctx, solid)}
