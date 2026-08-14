"""Cross-feature face survival: an extrude face survives a later boolean cut."""

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
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


def _face_normal_and_centroid_x(face):
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    face_f = TopoDS.Face_s(face)
    adaptor = BRepAdaptor_Surface(face_f)
    if adaptor.GetType() != 0:
        return None, None
    d = adaptor.Plane().Position().Direction()
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face_f, props)
    c = props.CentreOfMass()
    return (
        (round(d.X(), 3), round(d.Y(), 3), round(d.Z(), 3)),
        round(c.X(), 3),
    )


class TestCrossFeatureFace:
    def test_extrude_side_face_survives_cut(self):
        pytest.importorskip("cadquery")
        import cadquery as cq

        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
            tracked_extrude,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
            tracked_cut,
        )

        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)

        # Feature 1: extrude a box and name its +X side face.
        profile = cq.Workplane("XY").rect(40, 30).val()
        extrude = tracked_extrude(
            profile, (0, 0, 20),
            scope=TopologyCaptureScope(node_id="n_extrude", component_id="plate"),
        )
        feat_extrude = session.ensure_feature(session.ensure_component("plate"), "n_extrude")
        writer.write_batch(extrude.batch)

        plus_x = extrude.batch.construction_roles["+X"]
        assert plus_x is not None

        service = PersistentSelectionService(session)
        service.create(
            "x_side", plus_x, extrude.result.wrapped,
            SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )

        # Feature 2: cut a hole through the middle (does NOT touch the +X face).
        tool = cq.Workplane("XY").transformed(offset=(0, 0, -2)).box(8, 8, 24)
        cut = tracked_cut(
            extrude.result, tool.val(),
            scope=TopologyCaptureScope(node_id="n_cut", component_id="plate"),
        )
        feat_cut = session.ensure_feature(session.ensure_component("plate"), "n_cut")
        writer.write_batch(cut.batch)

        label_map = collect_tnaming_labels(session.design_root_label)
        resolution = service.solve("x_side", label_map)

        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        assert len(resolution.resolved_shapes) == 1

        normal, centroid_x = _face_normal_and_centroid_x(resolution.resolved_shapes[0])
        assert normal is not None
        assert abs(abs(normal[0]) - 1.0) < 0.01, f"expected X-normal, got {normal}"
        assert centroid_x > 0, f"expected the +X side face, got centroid_x={centroid_x}"

    def test_extrude_side_face_survives_cut_across_revisions(self, ascii_tmpdir):
        pytest.importorskip("cadquery")
        from pathlib import Path
        import cadquery as cq

        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
            tracked_extrude,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
            tracked_cut,
        )

        rev1_path = Path(ascii_tmpdir) / "cross_feature_rev1.xbf"

        # ---- Rev1: extrude + cut, then anchor a selection on the +X face. ----
        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        comp = session.ensure_component("plate")

        extrude1 = tracked_extrude(
            cq.Workplane("XY").rect(40, 30).val(), (0, 0, 20),
            scope=TopologyCaptureScope(node_id="n_extrude", component_id="plate"),
        )
        feat_e = session.ensure_feature(comp, "n_extrude")
        writer.write_batch(extrude1.batch)

        plus_x1 = extrude1.batch.construction_roles["+X"]
        assert plus_x1 is not None
        service = PersistentSelectionService(session)
        service.create(
            "x_side", plus_x1, extrude1.result.wrapped,
            SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )

        tool1 = cq.Workplane("XY").transformed(offset=(0, 0, -2)).box(8, 8, 24)
        cut1 = tracked_cut(
            extrude1.result, tool1.val(),
            scope=TopologyCaptureScope(node_id="n_cut", component_id="plate"),
        )
        feat_c = session.ensure_feature(comp, "n_cut")
        writer.write_batch(cut1.batch)

        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(rev1_path)
        session.close()

        # ---- Rev2: reopen, resize both features, then solve the old selection. ----
        session2 = OcafDocumentSession.open(rev1_path)
        writer2 = TopologyNamingWriter(session2)
        comp2 = session2.ensure_component("plate")
        feat_e2 = session2.ensure_feature(comp2, "n_extrude")
        feat_c2 = session2.ensure_feature(comp2, "n_cut")

        prev_e = session2.get_current_result_shape(feat_e2)
        assert prev_e is not None
        extrude2 = tracked_extrude(
            cq.Workplane("XY").rect(50, 40).val(), (0, 0, 22),
            scope=TopologyCaptureScope(node_id="n_extrude", component_id="plate"),
        )
        writer2.write_batch(extrude2.batch, previous_result=prev_e)

        tool2 = cq.Workplane("XY").transformed(offset=(0, 0, -2)).box(10, 10, 26)
        cut2 = tracked_cut(
            extrude2.result, tool2.val(),
            scope=TopologyCaptureScope(node_id="n_cut", component_id="plate"),
        )
        prev_c = session2.get_current_result_shape(feat_c2)
        writer2.write_batch(cut2.batch, previous_result=prev_c)

        label_map = collect_tnaming_labels(session2.design_root_label)
        service2 = PersistentSelectionService(session2)
        resolution = service2.solve("x_side", label_map)

        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        assert len(resolution.resolved_shapes) == 1
        normal, centroid_x = _face_normal_and_centroid_x(resolution.resolved_shapes[0])
        assert normal is not None
        assert abs(abs(normal[0]) - 1.0) < 0.01, f"expected X-normal, got {normal}"
        assert centroid_x > 0, f"expected the +X side face, got centroid_x={centroid_x}"
