"""OCP pipe sweeper — true 3D sweep using BRepOffsetAPI_MakePipe.

Uses OCP-native wire + profile face + MakePipe for smooth swept pipes.
Falls back to cylinder segments only when MakePipe fails.
"""

from __future__ import annotations
import math


def make_circular_pipe_along_path(
    path_points: list[tuple[float, float, float]],
    radius_mm: float,
):
    """Build a circular pipe along a 3D point path using true OCP sweep.

    2-point: single cylinder (fast path).
    3+ point: BRepOffsetAPI_MakePipe with 3D wire (smooth sweep).
    Falls back to segmented cylinders only on MakePipe failure.
    """
    import cadquery as cq

    if len(path_points) < 2:
        raise ValueError("Need at least 2 path points")

    if len(path_points) == 2:
        return _make_straight_pipe(path_points[0], path_points[1], radius_mm)

    # ── v6.2: Analysis-driven method selection ──
    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.path_analysis import (
        analyze_path_geometry,
    )
    analysis = analyze_path_geometry(path_points, radius_mm)

    # Pre-compute expected volume for validation
    expected_vol = math.pi * radius_mm**2 * analysis.total_length

    # Method dispatch based on path analysis recommendation
    if analysis.recommendation == "cylinder":
        # Straight path: single cylinder (already handled for 2-point above,
        # but also catches collinear multi-point paths)
        return _make_straight_pipe(path_points[0], path_points[-1], radius_mm)

    elif analysis.recommendation == "polyline_sweep":
        # Gentle single bend: polyline MakePipe is reliable
        try:
            result = _make_swept_pipe(path_points, radius_mm)
            actual = result.val().Volume() if hasattr(result, 'val') else result.Volume()
            if actual > 0 and actual / expected_vol > 0.90:
                return result
        except Exception:
            pass
        # Fall through to BSpline if polyline fails

    elif analysis.recommendation == "segmented":
        # Tight bends: go straight to segmented for guaranteed volume
        segments = [
            _make_straight_pipe(path_points[i], path_points[i + 1], radius_mm)
            for i in range(len(path_points) - 1)
        ]
        result = segments[0]
        for seg in segments[1:]:
            try:
                result = result.union(seg)
            except Exception:
                from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
                fuse = BRepAlgoAPI_Fuse(result.wrapped, seg.wrapped)
                fuse.Build()
                if fuse.IsDone():
                    result = cq.Solid(fuse.Shape())
        return result

    # BSpline sweep (default for complex paths without tight bends)
    try:
        result = _make_swept_pipe_bspline(path_points, radius_mm)
        actual = result.val().Volume() if hasattr(result, 'val') else result.Volume()
        if actual > 0 and actual / expected_vol > 0.90:
            return result
    except Exception:
        pass

    # Final fallback: segmented cylinders
    segments = [
        _make_straight_pipe(path_points[i], path_points[i + 1], radius_mm)
        for i in range(len(path_points) - 1)
    ]
    result = segments[0]
    for seg in segments[1:]:
        try:
            result = result.union(seg)
        except Exception:
            from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
            fuse = BRepAlgoAPI_Fuse(result.wrapped, seg.wrapped)
            fuse.Build()
            if fuse.IsDone():
                result = cq.Solid(fuse.Shape())
    return result


def _make_swept_pipe_bspline(
    path_points: list[tuple[float, float, float]],
    radius_mm: float,
):
    """Build a smooth swept pipe using BSpline path + MakePipe.

    BSpline interpolation avoids sharp corners that cause MakePipe
    self-intersection and volume loss in polyline sweeps.
    """
    import cadquery as cq
    from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Circ
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_MakeFace,
    )
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe

    # Build BSpline wire through all points
    ocp_pts = [gp_Pnt(p[0], p[1], p[2]) for p in path_points]
    spline_api = GeomAPI_PointsToBSpline(ocp_pts)
    if not spline_api.IsDone():
        raise RuntimeError("GeomAPI_PointsToBSpline failed")
    spline_curve = spline_api.Curve()
    spline_edge = BRepBuilderAPI_MakeEdge(spline_curve).Edge()
    wb = BRepBuilderAPI_MakeWire()
    wb.Add(spline_edge)
    if not wb.IsDone():
        raise RuntimeError("BSpline wire build failed")
    bspline_wire = wb.Wire()

    # Tangent at start for profile orientation
    p0 = path_points[0]
    p1 = path_points[1]
    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    t_len = math.sqrt(dx*dx + dy*dy + dz*dz)
    tangent = gp_Dir(dx / t_len, dy / t_len, dz / t_len)

    # Perpendicular reference direction
    z_ref = gp_Dir(0, 0, 1)
    if abs(tangent.Dot(z_ref)) > 0.99:
        z_ref = gp_Dir(1, 0, 0)
    x_dir = gp_Dir(
        tangent.Y() * z_ref.Z() - tangent.Z() * z_ref.Y(),
        tangent.Z() * z_ref.X() - tangent.X() * z_ref.Z(),
        tangent.X() * z_ref.Y() - tangent.Y() * z_ref.X(),
    )

    # Circular profile face at start, perpendicular to tangent
    ax2 = gp_Ax2(gp_Pnt(p0[0], p0[1], p0[2]), tangent, x_dir)
    circ = gp_Circ(ax2, radius_mm)
    circ_edge = BRepBuilderAPI_MakeEdge(circ).Edge()
    circ_wb = BRepBuilderAPI_MakeWire()
    circ_wb.Add(circ_edge)
    profile_face = BRepBuilderAPI_MakeFace(circ_wb.Wire()).Face()

    # Sweep along BSpline
    pipe = BRepOffsetAPI_MakePipe(bspline_wire, profile_face)
    pipe.Build()
    if not pipe.IsDone():
        raise RuntimeError("BRepOffsetAPI_MakePipe failed for BSpline pipe")

    return cq.Solid(pipe.Shape())


def _make_swept_pipe(
    path_points: list[tuple[float, float, float]],
    radius_mm: float,
):
    """Build a smooth swept pipe using OCP BRepOffsetAPI_MakePipe.

    1. Build 3D wire from path points
    2. Create circular profile face perpendicular to start tangent
    3. Sweep profile along wire using MakePipe
    """
    import cadquery as cq
    from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Circ
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_MakeFace,
    )
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe

    # Build 3D wire
    wb = BRepBuilderAPI_MakeWire()
    for i in range(len(path_points) - 1):
        p0, p1 = path_points[i], path_points[i + 1]
        edge = BRepBuilderAPI_MakeEdge(
            gp_Pnt(p0[0], p0[1], p0[2]),
            gp_Pnt(p1[0], p1[1], p1[2]),
        ).Edge()
        wb.Add(edge)
    if not wb.IsDone():
        raise RuntimeError("BRepBuilderAPI_MakeWire failed")
    wire = wb.Wire()

    # Compute start tangent for profile orientation
    p0 = path_points[0]
    p1 = path_points[1]
    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    t_len = math.sqrt(dx*dx + dy*dy + dz*dz)
    tangent = gp_Dir(dx / t_len, dy / t_len, dz / t_len)

    # Build reference direction perpendicular to tangent
    z_ref = gp_Dir(0, 0, 1)
    if abs(tangent.Dot(z_ref)) > 0.99:
        z_ref = gp_Dir(1, 0, 0)
    # Cross product to get a perpendicular direction
    x_dir = gp_Dir(
        tangent.Y() * z_ref.Z() - tangent.Z() * z_ref.Y(),
        tangent.Z() * z_ref.X() - tangent.X() * z_ref.Z(),
        tangent.X() * z_ref.Y() - tangent.Y() * z_ref.X(),
    )

    # Create circular profile face at path start, perpendicular to tangent
    ax2 = gp_Ax2(gp_Pnt(p0[0], p0[1], p0[2]), tangent, x_dir)
    circ = gp_Circ(ax2, radius_mm)
    circ_edge = BRepBuilderAPI_MakeEdge(circ).Edge()
    circ_wb = BRepBuilderAPI_MakeWire()
    circ_wb.Add(circ_edge)
    profile_face = BRepBuilderAPI_MakeFace(circ_wb.Wire()).Face()

    # True OCP sweep
    pipe = BRepOffsetAPI_MakePipe(wire, profile_face)
    pipe.Build()
    if not pipe.IsDone():
        raise RuntimeError("BRepOffsetAPI_MakePipe failed for swept pipe")

    return cq.Solid(pipe.Shape())


def _make_straight_pipe(
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    radius_mm: float,
):
    """Build a straight pipe between two 3D points (any orientation).

    Uses BRepPrimAPI_MakeCylinder at origin along Z, then rotate+translate
    to align with the target segment direction.
    """
    import cadquery as cq
    from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    length = math.sqrt(dx*dx + dy*dy + dz*dz)
    if length < 1e-9:
        raise ValueError("Pipe segment length too small")

    direction = gp_Dir(dx / length, dy / length, dz / length)
    z_axis = gp_Dir(0, 0, 1)

    cyl = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(0, 0, 0), z_axis), radius_mm, length
    ).Shape()
    solid = cq.Solid(cyl)

    # Rotate from Z-axis to target direction
    if not direction.IsEqual(z_axis, 0.001):
        cross_x = z_axis.Y() * direction.Z() - z_axis.Z() * direction.Y()
        cross_y = z_axis.Z() * direction.X() - z_axis.X() * direction.Z()
        cross_z = z_axis.X() * direction.Y() - z_axis.Y() * direction.X()
        angle = math.degrees(math.acos(min(1.0, z_axis.Dot(direction))))
        norm = math.sqrt(cross_x**2 + cross_y**2 + cross_z**2)
        if norm > 1e-12:
            solid = solid.rotate(
                (0, 0, 0),
                (cross_x/norm, cross_y/norm, cross_z/norm),
                angle,
            )

    solid = solid.translate((p0[0], p0[1], p0[2]))
    return solid
