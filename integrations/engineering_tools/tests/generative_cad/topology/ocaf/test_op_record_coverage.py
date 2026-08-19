"""Record-coverage tests: every tracked op must name all result faces/edges.

Covers extrude (rect + non-rect), revolve, shell, sweep, loft, and boolean
fuse/cut scenarios including overlapping/contained bodies, where fusion and
intersection create brand-new faces and edges. history_complete must be True
and every result face/edge must be covered by a role.
"""

from __future__ import annotations

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_common,
    tracked_cut,
    tracked_fuse,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.chamfer import (
    tracked_chamfer,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.fillet import (
    tracked_fillet,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.mirror import (
    tracked_mirror,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.pattern import (
    tracked_circular_pattern,
    tracked_linear_pattern,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.unify import (
    tracked_unify,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
    tracked_extrude,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.offset_sweep import (
    tracked_loft,
    tracked_shell,
    tracked_sweep,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.revolve import (
    tracked_revolve,
)


def _scope(node_id):
    return TopologyCaptureScope(node_id=node_id, component_id="part")


def _coverage(batch, result):
    """Return (faces_total, faces_covered, edges_total, edges_covered)."""
    role_faces = [
        s.shape for s in batch.face_roles.values()
        if getattr(s, "shape", None) is not None
    ]
    role_faces += [s for s in (batch.construction_roles or {}).values() if s is not None]
    role_edges = []
    for s in (batch.edge_roles or {}).values():
        sh = getattr(s, "shape", None)
        if sh is None:
            sh = s  # bare TopoDS_Edge for extrude/fillet/chamfer
        if sh is not None:
            role_edges.append(sh)

    faces = list(result.Faces())
    edges = list(result.Edges())
    cf = sum(
        1 for f in faces
        if any(f.wrapped.IsSame(x) or f.wrapped.IsPartner(x) for x in role_faces)
    )
    ce = sum(
        1 for e in edges
        if any(e.wrapped.IsSame(x) or e.wrapped.IsPartner(x) for x in role_edges)
    )
    return len(faces), cf, len(edges), ce


def _assert_full(name, batch, result):
    assert batch.history_complete, f"{name}: history_complete=False"
    nf, cf, ne, ce = _coverage(batch, result)
    assert cf == nf, f"{name}: faces covered {cf}/{nf}"
    assert ce == ne, f"{name}: edges covered {ce}/{ne}"


class TestOpRecordCoverage:
    def test_extrude_rect(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        r = tracked_extrude(
            cq.Workplane("XY").rect(20, 10).val(), (0, 0, 15), scope=_scope("n"),
        )
        _assert_full("extrude-rect", r.batch, r.result)

    def test_extrude_non_rect(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        tri = cq.Workplane("XY").polyline([(0, 0), (20, 0), (10, 15)]).close().val()
        r = tracked_extrude(tri, (0, 0, 15), scope=_scope("n"))
        _assert_full("extrude-triangle", r.batch, r.result)

    def test_revolve_ring(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        prof = cq.Workplane("XZ").polyline([(30, 0), (30, 25), (80, 25), (80, 0)]).close().val()
        r = tracked_revolve(
            cq.Face.makeFromWires(prof), (0, 0, 0), (0, 0, 1), 360, scope=_scope("n"),
        )
        _assert_full("revolve-ring", r.batch, r.result)

    def test_shell_closed(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        r = tracked_shell(
            cq.Workplane("XY").box(30, 30, 20).val(), 2.0,
            faces_to_remove=[], scope=_scope("n"),
        )
        _assert_full("shell-closed", r.batch, r.result)

    def test_sweep_circle(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
        from OCP.gp import gp_Pnt

        wb = BRepBuilderAPI_MakeWire()
        wb.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(0, 0, 40)).Edge())
        r = tracked_sweep(
            cq.Workplane("XY").circle(6).wire().val(), wb.Wire(), scope=_scope("n"),
        )
        _assert_full("sweep-circle", r.batch, r.result)

    def test_loft_circles(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        w1 = cq.Workplane("XY").circle(6).wire().val()
        w2 = cq.Workplane("XY").workplane(offset=30).circle(10).wire().val()
        r = tracked_loft([w1, w2], scope=_scope("n"))
        _assert_full("loft-circles", r.batch, r.result)

    def test_fuse_overlap_boxes(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        b1 = cq.Workplane("XY").box(30, 30, 30).val()
        b2 = cq.Workplane("XY").transformed(offset=(20, 0, 0)).box(30, 30, 30).val()
        r = tracked_fuse(b1, b2, scope=_scope("n"))
        _assert_full("fuse-overlap", r.batch, r.result)

    def test_fuse_contained(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        b1 = cq.Workplane("XY").box(30, 30, 30).val()
        b2 = cq.Workplane("XY").transformed(offset=(5, 0, 0)).box(10, 10, 10).val()
        r = tracked_fuse(b1, b2, scope=_scope("n"))
        _assert_full("fuse-contained", r.batch, r.result)

    def test_fuse_disc_and_box(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        prof = cq.Workplane("XZ").polyline([(20, 0), (20, 20), (60, 20), (60, 0)]).close().val()
        disc = tracked_revolve(
            cq.Face.makeFromWires(prof), (0, 0, 0), (0, 0, 1), 360, scope=_scope("d"),
        ).result
        box = cq.Workplane("XY").transformed(offset=(0, 30, 0)).box(20, 20, 20).val()
        r = tracked_fuse(disc, box, scope=_scope("n"))
        _assert_full("fuse-disc+box", r.batch, r.result)

    def test_fuse_base_and_rib(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        base = cq.Workplane("XY").box(40, 40, 10).val()
        rib = tracked_extrude(
            cq.Workplane("XY").transformed(offset=(20, 0, 5)).rect(15, 40).val(),
            (0, 0, 25), scope=_scope("r"),
        ).result
        r = tracked_fuse(base, rib, scope=_scope("n"))
        _assert_full("fuse-base+rib", r.batch, r.result)

    def test_cut_disc_and_box(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        prof = cq.Workplane("XZ").polyline([(20, 0), (20, 20), (60, 20), (60, 0)]).close().val()
        disc = tracked_revolve(
            cq.Face.makeFromWires(prof), (0, 0, 0), (0, 0, 1), 360, scope=_scope("d"),
        ).result
        tool = cq.Workplane("XY").transformed(offset=(40, 0, 0)).box(30, 30, 40).val()
        r = tracked_cut(disc, tool, scope=_scope("n"))
        _assert_full("cut-disc+box", r.batch, r.result)


class TestMoreOpRecordCoverage:
    def test_common_box_and_cylinder(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        box = cq.Workplane("XY").box(20, 20, 20).val()
        cyl = cq.Workplane("XY").cylinder(30, 8, centered=(True, True, True)).val()
        r = tracked_common(box, cyl, scope=_scope("n"))
        _assert_full("common", r.batch, r.result)

    def test_chamfer_box_multi_edge(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from OCP.TopoDS import TopoDS

        box = cq.Workplane("XY").box(20, 20, 20).val()
        edges = [TopoDS.Edge_s(e.wrapped) for e in list(box.Edges())[:3]]
        r = tracked_chamfer(box, edges, 2.0, scope=_scope("n"))
        _assert_full("chamfer", r.batch, r.result)

    def test_fillet_box_multi_edge(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from OCP.TopoDS import TopoDS

        box = cq.Workplane("XY").box(20, 20, 20).val()
        edges = [TopoDS.Edge_s(e.wrapped) for e in list(box.Edges())[:3]]
        r = tracked_fillet(box, edges, 2.0, scope=_scope("n"))
        _assert_full("fillet", r.batch, r.result)

    def test_mirror_box(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        box = cq.Workplane("XY").box(20, 20, 20).val()
        r = tracked_mirror(box, (0, 0, 0), (1, 0, 0), scope=_scope("n"))
        _assert_full("mirror", r.batch, r.result)

    def test_linear_pattern(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        box = cq.Workplane("XY").box(20, 10, 5).val()
        r = tracked_linear_pattern(box, (1, 0, 0), 3, 30, scope=_scope("n"))
        _assert_full("linear-pattern", r.batch, r.result)

    def test_circular_pattern(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        box = cq.Workplane("XY").box(10, 10, 10).val()
        r = tracked_circular_pattern(
            box, (0, 0, 0), (0, 0, 1), 4, radius_mm=40, scope=_scope("n"),
        )
        _assert_full("circular-pattern", r.batch, r.result)

    def test_unify_seam_solid(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        from OCP.BRepBuilderAPI import (
            BRepBuilderAPI_MakeEdge,
            BRepBuilderAPI_MakeFace,
            BRepBuilderAPI_MakeSolid,
            BRepBuilderAPI_MakeWire,
            BRepBuilderAPI_Sewing,
        )
        from OCP.ShapeFix import ShapeFix_Shape
        from OCP.gp import gp_Pnt

        def poly_face(pts):
            wb = BRepBuilderAPI_MakeWire()
            for i in range(len(pts)):
                a = pts[i]
                b = pts[(i + 1) % len(pts)]
                wb.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge())
            fb = BRepBuilderAPI_MakeFace(wb.Wire(), False)
            fb.Build()
            return fb.Face()

        bottom = poly_face([(-10, -10, 0), (10, -10, 0), (10, 10, 0), (-10, 10, 0)])
        tl = poly_face([(-10, -10, 10), (0, -10, 10), (0, 10, 10), (-10, 10, 10)])
        tr = poly_face([(0, -10, 10), (10, -10, 10), (10, 10, 10), (0, 10, 10)])
        front = poly_face([(-10, -10, 0), (10, -10, 0), (10, -10, 10), (-10, -10, 10)])
        back = poly_face([(10, 10, 0), (-10, 10, 0), (-10, 10, 10), (10, 10, 10)])
        left = poly_face([(-10, -10, 0), (-10, 10, 0), (-10, 10, 10), (-10, -10, 10)])
        right = poly_face([(10, -10, 0), (10, 10, 0), (10, 10, 10), (10, -10, 10)])
        sewer = BRepBuilderAPI_Sewing(1e-5)
        for f in (bottom, tl, tr, front, back, left, right):
            sewer.Add(f)
        sewer.Perform()
        shell = cq.Shape.cast(sewer.SewedShape())
        solid_builder = BRepBuilderAPI_MakeSolid(shell.wrapped)
        solid = solid_builder.Solid() if solid_builder.IsDone() else shell.wrapped
        fix = ShapeFix_Shape(solid)
        fix.Perform()
        seam = cq.Shape.cast(fix.Shape())

        r = tracked_unify(seam, scope=_scope("n"))
        _assert_full("unify-seam", r.batch, r.result)
