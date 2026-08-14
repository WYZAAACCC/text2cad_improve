"""Revolve role faces survive across revisions."""

from pathlib import Path

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


def _make_revolve_profile(r_mm: float, z_max_mm: float):
    import cadquery as cq
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    wp = (
        cq.Workplane("XZ")
        .moveTo(r_mm, 0)
        .lineTo(r_mm, z_max_mm)
        .lineTo(0, z_max_mm)
        .lineTo(0, 0)
        .close()
    )
    wire = wp.wire().val()
    fb = BRepBuilderAPI_MakeFace(wire.wrapped, False)
    fb.Build()
    return cq.Shape.cast(fb.Face())


def _face_normal_and_centroid_z(face):
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
        round(c.Z(), 3),
    )


class TestRevolveFaceLineage:
    def test_revolve_top_cap_survives_across_revisions(self, ascii_tmpdir):
        pytest.importorskip("cadquery")

        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.revolve import (
            tracked_revolve,
        )

        rev1_path = Path(ascii_tmpdir) / "revolve_rev1.xbf"

        # ---- Rev1: revolve a disc and anchor a selection on the top cap. ----
        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        comp = session.ensure_component("disk")
        feat = session.ensure_feature(comp, "n_revolve")

        profile1 = _make_revolve_profile(20, 30)
        revolve1 = tracked_revolve(
            profile1, (0, 0, 0), (0, 0, 1), 360,
            scope=TopologyCaptureScope(node_id="n_revolve", component_id="disk"),
        )
        writer.write_batch(revolve1.batch)

        top_cap1 = revolve1.batch.construction_roles["end_cap"]
        assert top_cap1 is not None
        service = PersistentSelectionService(session)
        service.create(
            "top", top_cap1, revolve1.result.wrapped,
            SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )

        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(rev1_path)
        session.close()

        # ---- Rev2: reopen, resize the disc, then solve the old selection. ----
        session2 = OcafDocumentSession.open(rev1_path)
        writer2 = TopologyNamingWriter(session2)
        comp2 = session2.ensure_component("disk")
        feat2 = session2.ensure_feature(comp2, "n_revolve")

        prev = session2.get_current_result_shape(feat2)
        assert prev is not None
        profile2 = _make_revolve_profile(25, 35)
        revolve2 = tracked_revolve(
            profile2, (0, 0, 0), (0, 0, 1), 360,
            scope=TopologyCaptureScope(node_id="n_revolve", component_id="disk"),
        )
        writer2.write_batch(revolve2.batch, previous_result=prev)

        label_map = collect_tnaming_labels(session2.design_root_label)
        service2 = PersistentSelectionService(session2)
        resolution = service2.solve("top", label_map)

        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        assert len(resolution.resolved_shapes) == 1
        normal, centroid_z = _face_normal_and_centroid_z(resolution.resolved_shapes[0])
        assert normal is not None
        assert abs(abs(normal[2]) - 1.0) < 0.01, f"expected Z-normal, got {normal}"
        assert centroid_z > 0, f"expected the top cap (centroid_z>0), got {centroid_z}"
