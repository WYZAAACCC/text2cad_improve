"""OCP 3D wire builders — bypass CadQuery XY-plane limitations.

Fully supports vertical/horizontal/angled/spline 3D wire paths.
"""

from __future__ import annotations


def make_3d_polyline_wire(points: list[tuple[float, float, float]]):
    """Build a TopoDS_Wire from 3D points using straight edges.

    Each segment uses BRepBuilderAPI_MakeEdge(p1, p2) — fully 3D.
    Vertical segments (x0==x1 and y0==y1) are fully supported.
    """
    from OCP.gp import gp_Pnt
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire

    if len(points) < 2:
        raise ValueError("Need at least 2 points for polyline wire")

    wb = BRepBuilderAPI_MakeWire()
    for i in range(len(points) - 1):
        p0, p1 = points[i], points[i + 1]
        edge = BRepBuilderAPI_MakeEdge(
            gp_Pnt(p0[0], p0[1], p0[2]),
            gp_Pnt(p1[0], p1[1], p1[2]),
        ).Edge()
        wb.Add(edge)

    if not wb.IsDone():
        raise RuntimeError("BRepBuilderAPI_MakeWire failed for 3D polyline")
    return wb.Wire()


def make_3d_spline_wire(points: list[tuple[float, float, float]]):
    """Build a TopoDS_Wire from 3D points using B-spline interpolation.

    Uses GeomAPI_PointsToBSpline to create a curve passing through all points.
    """
    from OCP.gp import gp_Pnt
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire

    if len(points) < 2:
        raise ValueError("Need at least 2 points for spline wire")

    ocp_pts = [gp_Pnt(p[0], p[1], p[2]) for p in points]
    spline_api = GeomAPI_PointsToBSpline(ocp_pts)
    if not spline_api.IsDone():
        raise RuntimeError("GeomAPI_PointsToBSpline failed")
    spline = spline_api.Curve()
    edge = BRepBuilderAPI_MakeEdge(spline).Edge()
    wb = BRepBuilderAPI_MakeWire()
    wb.Add(edge)
    return wb.Wire()
