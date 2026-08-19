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
    tracked_cut,
    tracked_fuse,
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
