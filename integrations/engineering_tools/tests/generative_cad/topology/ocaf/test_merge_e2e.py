"""Merge (N→1) fix verification with process monitoring."""

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    TopologyCaptureScope,
)


def _rect_face(x1, x2, y1, y2, z):
    from OCP.gp import gp_Pnt
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_MakeFace,
    )

    wb = BRepBuilderAPI_MakeWire()
    pts = [(x1, y1, z), (x2, y1, z), (x2, y2, z), (x1, y2, z)]
    for i in range(4):
        a = pts[i]
        b = pts[(i + 1) % 4]
        wb.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge())
    fb = BRepBuilderAPI_MakeFace(wb.Wire(), False)
    fb.Build()
    return fb.Face()


def _sew(faces):
    import cadquery as cq
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing

    sewer = BRepBuilderAPI_Sewing(1e-5)
    for f in faces:
        sewer.Add(f)
    sewer.Perform()
    return cq.Shape.cast(sewer.SewedShape())


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
    """Build a closed box whose top face is split into two coplanar faces.

    The seam runs along x=0 on the z=10 face, so ``ShapeUpgrade_UnifySameDomain``
    merges the two top faces back into one. This gives a valid solid context for
    ``TNaming_Selector`` (an open shell makes Solve return False).
    """
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


class TestMergeEndToEnd:
    def test_merge_records_modified_not_deleted(self):
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.unify import (
            tracked_unify,
        )

        left = _rect_face(-10, 0, -10, 10, 10)
        right = _rect_face(0, 10, -10, 10, 10)
        shell = _sew([left, right])

        print(f"[merge] shell faces before unify: {len(list(shell.Faces()))}")
        unified = tracked_unify(shell, scope=TopologyCaptureScope(node_id="n_unify"))
        print(f"[merge] shell faces after unify: {len(list(unified.result.Faces()))}")

        by_kind = {}
        for r in unified.batch.relations:
            by_kind.setdefault(r.kind.value, []).append(r.source_key)
            print(f"[merge] relation kind={r.kind.value} source={r.source_key}")
        print(f"[merge] relation summary: { {k: len(v) for k, v in by_kind.items()} }")

        # The merge must be recorded as MODIFIED (identity continues into the
        # merged face), not DELETED.
        assert EvolutionKind.DELETED.value not in by_kind
        assert EvolutionKind.MODIFIED.value in by_kind
        assert len(list(unified.result.Faces())) == 1

    def test_merge_selection_solve_unique(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
            OcafDocumentSession,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
            TopologyNamingWriter,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
            PersistentSelectionService,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
            collect_tnaming_labels,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            SelectionPolicy,
            TopologyEntityKind,
            SelectionResolutionStatus,
            TopologyCaptureScope,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
            ROLE_TAG_BASE,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.unify import (
            tracked_unify,
        )

        solid = _seam_solid()
        assert solid.isValid()
        assert len(list(solid.Faces())) == 7

        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        comp = session.ensure_component("comp")
        feat = session.ensure_feature(comp, "n_solid")
        writer.write_feature_result(feat, solid.wrapped)

        # The two coplanar top faces must be individually named so the selector
        # can track them at face granularity (a whole-body result alone is not
        # enough for a sub-face selection in OCP 7.8.1.1).
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
            solid, scope=TopologyCaptureScope(node_id="n_unify", component_id="comp")
        )
        writer.write_batch(unified.batch)
        assert len(list(unified.result.Faces())) == 6

        label_map = collect_tnaming_labels(session.design_root_label)
        resolution = svc.solve("seam_left", label_map)
        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        assert len(resolution.resolved_shapes) == 1

        merged = cq.Shape.cast(resolution.resolved_shapes[0])
        assert abs(merged.Center().z - 10) < 1e-4
        assert abs(merged.Area() - 400.0) < 0.01
        session.close()
