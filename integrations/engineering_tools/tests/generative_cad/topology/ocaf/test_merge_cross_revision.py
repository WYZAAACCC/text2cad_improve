"""Merge (N→1) survives a cross-revision save/reopen cycle."""

from pathlib import Path

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
    collect_tnaming_labels,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
    OcafDocumentSession,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionPolicy,
    SelectionResolutionStatus,
    TopologyCaptureScope,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
    PersistentSelectionService,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.unify import (
    tracked_unify,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
    TopologyNamingWriter,
)


def _poly_face(pts):
    from OCP.gp import gp_Pnt
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_MakeFace,
    )

    wb = BRepBuilderAPI_MakeWire()
    for i in range(len(pts)):
        a = pts[i]
        b = pts[(i + 1) % len(pts)]
        wb.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge())
    fb = BRepBuilderAPI_MakeFace(wb.Wire(), False)
    fb.Build()
    return fb.Face()


def _seam_solid():
    """Build a closed box whose top face is split into two coplanar faces."""
    import cadquery as cq
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Shape

    bottom = _poly_face([(-10, -10, 0), (10, -10, 0), (10, 10, 0), (-10, 10, 0)])
    top_left = _poly_face([(-10, -10, 10), (0, -10, 10), (0, 10, 10), (-10, 10, 10)])
    top_right = _poly_face([(0, -10, 10), (10, -10, 10), (10, 10, 10), (0, 10, 10)])
    front = _poly_face([(-10, -10, 0), (10, -10, 0), (10, -10, 10), (-10, -10, 10)])
    back = _poly_face([(10, 10, 0), (-10, 10, 0), (-10, 10, 10), (10, 10, 10)])
    left = _poly_face([(-10, -10, 0), (-10, 10, 0), (-10, 10, 10), (-10, -10, 10)])
    right = _poly_face([(10, -10, 0), (10, 10, 0), (10, 10, 10), (10, -10, 10)])

    sewer = BRepBuilderAPI_Sewing(1e-5)
    for face in (bottom, top_left, top_right, front, back, left, right):
        sewer.Add(face)
    sewer.Perform()

    shell = cq.Shape.cast(sewer.SewedShape())
    solid_builder = BRepBuilderAPI_MakeSolid(shell.wrapped)
    solid = solid_builder.Solid() if solid_builder.IsDone() else shell.wrapped

    fix = ShapeFix_Shape(solid)
    fix.Perform()
    return cq.Shape.cast(fix.Shape())


class TestMergeCrossRevision:
    def test_merged_face_survives_reopen(self, ascii_tmpdir):
        pytest.importorskip("cadquery")
        import cadquery as cq

        from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
            ROLE_TAG_BASE,
        )

        xbf = Path(ascii_tmpdir) / "merge_rev.xbf"

        solid = _seam_solid()
        assert solid.isValid()
        assert len(list(solid.Faces())) == 7

        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        comp = session.ensure_component("comp")
        feat = session.ensure_feature(comp, "n_solid")
        writer.write_feature_result(feat, solid.wrapped)

        top_faces = sorted(
            [f for f in solid.Faces() if abs(f.Center().z - 10) < 1e-4],
            key=lambda f: f.Center().x,
        )
        assert len(top_faces) == 2
        writer.write_role_result(feat, ROLE_TAG_BASE, top_faces[0].wrapped)
        writer.write_role_result(feat, ROLE_TAG_BASE + 1, top_faces[1].wrapped)

        svc = PersistentSelectionService(session)
        svc.create(
            "seam_left",
            top_faces[0].wrapped,
            solid.wrapped,
            SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )

        unified = tracked_unify(
            solid,
            scope=TopologyCaptureScope(node_id="n_unify", component_id="comp"),
        )
        writer.write_batch(unified.batch)
        assert len(list(unified.result.Faces())) == 6

        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(xbf)
        session.close()

        # Cross-process reopen: the merged face must still resolve uniquely.
        session2 = OcafDocumentSession.open(xbf)
        svc2 = PersistentSelectionService(session2)
        resolution = svc2.solve(
            "seam_left", collect_tnaming_labels(session2.design_root_label),
        )
        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        assert len(resolution.resolved_shapes) == 1
        merged = cq.Shape.cast(resolution.resolved_shapes[0])
        assert abs(merged.Center().z - 10) < 1e-4
        assert abs(merged.Area() - 400.0) < 0.01
        session2.close()
