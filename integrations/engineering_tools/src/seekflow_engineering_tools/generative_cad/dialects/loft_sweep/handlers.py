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


def _make_3d_polyline_wire(pts: list) -> "TopoDS_Wire":
    """Build a true 3D wire from points using OCP native API.

    CadQuery Workplane.lineTo/moveTo on XY plane drops the Z coordinate.
    This helper uses OCP directly to preserve full 3D coordinates.
    """
    from OCP.gp import gp_Pnt
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    wire_builder = BRepBuilderAPI_MakeWire()
    for i in range(len(pts) - 1):
        p1 = gp_Pnt(pts[i].x, pts[i].y, pts[i].z)
        p2 = gp_Pnt(pts[i + 1].x, pts[i + 1].y, pts[i + 1].z)
        edge = BRepBuilderAPI_MakeEdge(p1, p2).Edge()
        wire_builder.Add(edge)
    return wire_builder.Wire()


def _make_3d_spline_wire(pts: list) -> "TopoDS_Wire":
    """Build a 3D BSpline wire through all points using OCP."""
    from OCP.gp import gp_Pnt
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    ocp_pts = [gp_Pnt(p.x, p.y, p.z) for p in pts]
    spline = GeomAPI_PointsToBSpline(ocp_pts).Curve()
    edge = BRepBuilderAPI_MakeEdge(spline).Edge()
    wire_builder = BRepBuilderAPI_MakeWire()
    wire_builder.Add(edge)
    return wire_builder.Wire()


def handle_sweep_profile(node, ctx) -> dict:
    """Sweep a 2D profile along a previously defined 3D path."""
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
        # Build path — try CadQuery first (handles 2D and simple 3D)
        if len(pts) == 2:
            path_wire = cq.Workplane("XY").moveTo(pts[0].x, pts[0].y).lineTo(pts[1].x, pts[1].y)
        else:
            path_wire = cq.Workplane("XY").spline(pts)

        # Self-intersection check
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


def _estimate_helix_sweep_volume(radius, profile_r, turns, total_z):
    """Theoretical helix volume = profile area × centerline length."""
    centerline_len = math.sqrt(
        (2.0 * math.pi * radius * turns) ** 2 + total_z ** 2
    )
    return math.pi * profile_r ** 2 * centerline_len


def _build_helix_wire_ocp(radius, total_z, turns, sample_n=720):
    """Build a 3D helix as TopoDS_Wire using OCP native API.

    Bypasses CadQuery parametricCurve which produces polyline-approximated
    paths that cause BRepOffsetAPI_MakePipeShell to fail on multi-turn helices.
    """
    from OCP.gp import gp_Pnt
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire

    n_pts = sample_n + 1
    arr = TColgp_Array1OfPnt(1, n_pts)
    for i in range(n_pts):
        t = i / sample_n
        angle = 2.0 * math.pi * turns * t
        z = total_z * t
        arr.SetValue(i + 1, gp_Pnt(
            radius * math.cos(angle),
            radius * math.sin(angle),
            z,
        ))

    spline_api = GeomAPI_PointsToBSpline(arr)
    if not spline_api.IsDone():
        raise RuntimeError("GeomAPI_PointsToBSpline failed")
    spline = spline_api.Curve()
    edge = BRepBuilderAPI_MakeEdge(spline).Edge()
    wire_builder = BRepBuilderAPI_MakeWire()
    wire_builder.Add(edge)
    return wire_builder.Wire()


def handle_helix_sweep(node, ctx) -> dict:
    """Sweep a profile along a helical path (spring/thread).

    v5.2: Uses OCP native GeomAPI_PointsToBSpline + BRepOffsetAPI_MakePipe
    to bypass CadQuery parametricCurve sweep bugs that produce ~2-5% volume.
    """
    import cadquery as cq

    params = node.params
    turns = float(params.get("turns", 1.0))
    radius = float(params.get("radius_mm", 10))
    profile_r = float(params.get("profile_radius_mm", 2))
    pitch = float(params.get("pitch_mm", 0.0))
    height_raw = params.get("height_mm")
    variable = params.get("variable_pitch", False)

    # ── Parameter validation (fail-fast) ──
    if turns <= 0:
        raise RuntimeError("helix_sweep requires turns > 0")
    if radius <= 0:
        raise RuntimeError("helix_sweep requires radius_mm > 0")
    if profile_r <= 0:
        raise RuntimeError("helix_sweep requires profile_radius_mm > 0")

    if height_raw is not None:
        total_z = float(height_raw)
    elif pitch > 0:
        total_z = pitch * turns
    else:
        raise RuntimeError("helix_sweep requires height_mm or positive pitch_mm")
    if total_z <= 0:
        raise RuntimeError("helix_sweep requires positive total height")

    # Coil self-intersection check
    if pitch > 0 and profile_r >= pitch * 0.45:
        ctx.warnings.append(
            f"helix_sweep on '{node.id}': profile_radius_mm ({profile_r:.1f}) "
            f">= 0.45*pitch_mm ({pitch*0.45:.1f}). Coils may self-intersect."
        )

    try:
        # ── Build helix wire using OCP native API ──
        sample_n = max(360, int(math.ceil(turns * 60)))
        helix_wire = _build_helix_wire_ocp(radius, total_z, turns, sample_n)

        # ── Build profile as a face for BRepOffsetAPI_MakePipe ──
        profile = cq.Workplane("XZ").center(radius, 0).circle(profile_r)
        profile_face = profile.val()

        # ── Try OCP BRepOffsetAPI_MakePipe first ──
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe
        profile_shape = profile_face.wrapped if hasattr(profile_face, 'wrapped') else profile_face
        pipe = BRepOffsetAPI_MakePipe(helix_wire, profile_shape)
        pipe.Build()

        if pipe.IsDone():
            solid = cq.Solid(pipe.Shape())
        else:
            # ── Fallback: CadQuery parametricCurve sweep ──
            ctx.warnings.append(
                f"helix_sweep on '{node.id}': OCP MakePipe failed, "
                f"falling back to CadQuery sweep (may have reduced volume)"
            )
            helix = cq.Workplane("XY").parametricCurve(
                lambda t: (
                    radius * math.cos(2.0 * math.pi * turns * t),
                    radius * math.sin(2.0 * math.pi * turns * t),
                    total_z * t,
                ),
                N=max(200, int(math.ceil(turns * 25))),
            )
            profile = cq.Workplane("XZ").center(radius, 0).circle(profile_r)
            solid = profile.sweep(helix)

        # ── Volume verification ──
        expected_v = _estimate_helix_sweep_volume(radius, profile_r, turns, total_z)
        # solid may be CadQuery Solid or Workplane; get actual shape
        actual_solid = solid.val() if hasattr(solid, 'val') else solid
        actual_v = actual_solid.Volume() if hasattr(actual_solid, 'Volume') else 0.0

        if actual_v <= 0:
            raise RuntimeError(
                f"helix_sweep on '{node.id}': non-positive volume ({actual_v:.2f})"
            )

        ratio = actual_v / expected_v if expected_v > 0 else 0
        if ratio < 0.55 or ratio > 1.65:
            ctx.warnings.append(
                f"helix_sweep on '{node.id}': volume ratio={ratio:.3f} "
                f"(actual={actual_v:.0f}, expected={expected_v:.0f})."
            )
            # Only fail-closed if strict_semantic is explicitly True
            # (default is False to allow CadQuery fallback)
            if params.get("strict_semantic", False):
                raise RuntimeError(
                    f"helix_sweep: volume deviation too large (ratio={ratio:.3f})"
                )
            else:
                ctx.degraded_features.append({
                    "node_id": node.id, "op": "helix_sweep",
                    "reason": f"volume deviation (ratio={ratio:.3f})",
                })

    except Exception as e:
        raise RuntimeError(f"helix_sweep failed on '{node.id}': {e}")

    return {"body": _store_solid(node, ctx, solid)}
