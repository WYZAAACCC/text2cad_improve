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
    """Return unmodified body with warning when operation fails.

    v6.3: Required features hard fail — only optional/decorative features may degrade.
    """
    if getattr(node, "required", True):
        raise RuntimeError(
            f"Required operation '{op_name}' failed on '{node.id}': "
            f"geometry does not support this operation and degradation is not allowed. "
            f"Fix the parameters or mark the node as required=False with "
            f"degradation_policy='may_skip_with_warning' if this feature is decorative."
        )
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
    """Sweep a 2D circular profile along a previously defined 3D path.

    v6.1: Uses OCP-native 3D pipe builder (make_circular_pipe_along_path)
    which handles pure vertical, horizontal, and angled straight pipe segments,
    bypassing CadQuery's XY-workplane Z-dropping limitation.
    Falls back to CadQuery spline sweep for non-circular profiles.
    """
    import cadquery as cq
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object

    path_data = resolve_input_object(node, ctx, 0)
    params = node.params
    shape = params.get("shape", "circle")
    radius = float(params.get("radius_mm", 5))
    width = float(params.get("width_mm", 10))
    height = float(params.get("height_mm", 10))

    # Convert path point dicts to (x, y, z) tuples
    pts: list[tuple[float, float, float]] = []
    for p in path_data:
        x = float(p.get("x_mm", p.get("x", 0))) if isinstance(p, dict) else float(p[0])
        y = float(p.get("y_mm", p.get("y", 0))) if isinstance(p, dict) else float(p[1])
        z = float(p.get("z_mm", p.get("z", 0))) if isinstance(p, dict) else float(p[2])
        pts.append((x, y, z))

    if len(pts) < 2:
        raise ValueError("Need at least 2 path points for sweep")

    # Self-intersection check (same as before)
    for i in range(len(pts) - 2):
        for j in range(i + 2, len(pts) - 1):
            di = (pts[i][0]-pts[j][0])**2 + (pts[i][1]-pts[j][1])**2 + (pts[i][2]-pts[j][2])**2
            if di < 0.01:
                raise RuntimeError(
                    f"Sweep path self-intersects: points {i} and {j} are {di**0.5:.4f}mm apart"
                )

    try:
        if shape == "circle":
            # v6.1: OCP-native 3D pipe (handles vertical/horizontal/angled)
            from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.ocp_pipe import (
                make_circular_pipe_along_path,
            )
            solid = make_circular_pipe_along_path(pts, radius)
        else:
            # Non-circular: CadQuery fallback
            cq_pts = [cq.Vector(p[0], p[1], p[2]) for p in pts]
            if len(pts) == 2:
                path_wire = cq.Workplane("XY").moveTo(
                    cq_pts[0].x, cq_pts[0].y
                ).lineTo(cq_pts[1].x, cq_pts[1].y)
            else:
                path_wire = cq.Workplane("XY").spline(cq_pts)
            profile = cq.Workplane("XZ").rect(width, height)
            solid = profile.sweep(path_wire)
    except Exception as e:
        raise RuntimeError(f"sweep_profile failed on '{node.id}': {e}")

    return {"body": _store_solid(node, ctx, solid)}


def handle_loft_sections(node, ctx) -> dict:
    """Loft between multiple cross-sections at different 3D positions.

    v6.3: Uses native OCP ThruSections (ocp_loft.native_loft_sections) for
    heterogeneous topology sections (circle→rectangle→circle). Falls back
    to CadQuery .loft() for backward compatibility.
    """
    import cadquery as cq

    sections = node.params.get("sections", [])
    if len(sections) < 2:
        raise ValueError("Need at least 2 sections for loft")

    ruled = node.params.get("ruled", False)
    sample_n = int(node.params.get("sample_n", 64))
    continuity = node.params.get("continuity", "G0")

    continuity_note = ""
    if continuity in ("G1", "G2"):
        continuity_note = (
            f"continuity={continuity} requested but OCCT only supports G0. "
        )

    # ── v6.3: Preferred path — native OCP loft ──
    try:
        from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.ocp_loft import (
            native_loft_sections,
        )
        solid = native_loft_sections(sections, ruled=ruled, sample_n=sample_n)
        if continuity_note:
            ctx.warnings.append(
                f"loft_sections on '{node.id}': {continuity_note}"
                f"Native OCP loft used."
            )
        return {"body": _store_solid(node, ctx, solid)}
    except Exception as native_exc:
        ctx.warnings.append(
            f"loft_sections on '{node.id}': native OCP loft failed "
            f"({native_exc}), falling back to CadQuery loft"
        )

    # ── Fallback: CadQuery loft (backward compatible) ──
    try:
        wires = []
        for sec in sections:
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

        solid = cq.Workplane("XY").add(wires).toPending().loft(ruled=ruled)
        if continuity_note:
            ctx.warnings.append(
                f"loft_sections on '{node.id}': {continuity_note}"
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


def _build_helix_wire_ocp(radius, total_z, turns, sample_n=720, z_start=0.0):
    """Build a 3D helix as TopoDS_Wire using OCP native API.

    Bypasses CadQuery parametricCurve which produces polyline-approximated
    paths that cause BRepOffsetAPI_MakePipeShell to fail on multi-turn helices.

    v6.1: z_start parameter for segmented helix sweep.
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
        z = z_start + total_z * t
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
        # ── Profile for sweep ──
        profile = cq.Workplane("XZ").center(radius, 0).circle(profile_r)
        profile_face = profile.val()
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe

        # ── v6.1: Segmented sweep for long helices (>8 turns) ──
        MAX_TURNS_ONE_SHOT = 8
        MAX_TURNS_PER_SEG = 3

        if turns <= MAX_TURNS_ONE_SHOT:
            # One-shot OCP MakePipe
            sample_n = max(360, int(math.ceil(turns * 60)))
            helix_wire = _build_helix_wire_ocp(radius, total_z, turns, sample_n)
            profile_shape = profile_face.wrapped if hasattr(profile_face, 'wrapped') else profile_face
            pipe = BRepOffsetAPI_MakePipe(helix_wire, profile_shape)
            pipe.Build()

            if pipe.IsDone():
                solid = cq.Solid(pipe.Shape())
            else:
                # Fallback: CadQuery parametricCurve sweep
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
                solid = profile.sweep(helix)
        else:
            # ── v6.1: Segmented sweep for long helices ──
            n_segs = int(math.ceil(turns / MAX_TURNS_PER_SEG))
            turns_per_seg = turns / n_segs
            z_per_seg = total_z / n_segs
            seg_solids = []

            for i in range(n_segs):
                z_start = z_per_seg * i
                seg_z = z_per_seg
                seg_turns = turns_per_seg
                seg_sample_n = max(360, int(math.ceil(seg_turns * 60)))
                seg_wire = _build_helix_wire_ocp(radius, seg_z, seg_turns, seg_sample_n, z_start=z_start)
                pf = profile_face.val() if hasattr(profile_face, 'val') else profile_face
                ps = pf.wrapped if hasattr(pf, 'wrapped') else pf
                pipe = BRepOffsetAPI_MakePipe(seg_wire, ps)
                pipe.Build()
                if not pipe.IsDone():
                    raise RuntimeError(
                        f"helix_sweep segment {i+1}/{n_segs} OCP MakePipe failed"
                    )
                seg_solids.append(cq.Solid(pipe.Shape()))

            # Fuse segments
            solid = seg_solids[0]
            for seg in seg_solids[1:]:
                try:
                    solid = solid.union(seg)
                except Exception:
                    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
                    fuse = BRepAlgoAPI_Fuse(solid.wrapped, seg.wrapped)
                    fuse.Build()
                    if fuse.IsDone():
                        solid = cq.Solid(fuse.Shape())
                    else:
                        raise RuntimeError("helix_sweep segment fuse failed")

            ctx.warnings.append(
                f"helix_sweep on '{node.id}': segmented sweep ({n_segs} segments × "
                f"{turns_per_seg:.1f} turns, fused)"
            )

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
