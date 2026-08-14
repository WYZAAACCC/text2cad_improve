"""Post-generation selection: create a selection on a role face after the model exists."""

from pathlib import Path

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
    PersistentSelectionService,
    create_selection_from_role,
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


def _make_annular_profile(r_outer: float, r_inner: float, z_max: float):
    import cadquery as cq
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    wp = (
        cq.Workplane("XZ")
        .moveTo(r_outer, 0)
        .lineTo(r_outer, z_max)
        .lineTo(r_inner, z_max)
        .lineTo(r_inner, 0)
        .close()
    )
    wire = wp.wire().val()
    fb = BRepBuilderAPI_MakeFace(wire.wrapped, False)
    fb.Build()
    return cq.Shape.cast(fb.Face())


def _face_cylinder_radius(face):
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    face_f = TopoDS.Face_s(face)
    adaptor = BRepAdaptor_Surface(face_f)
    if adaptor.GetType() != 1:
        return None
    return round(float(adaptor.Cylinder().Radius()), 3)


class TestPostGenerationSelection:
    def test_create_selection_on_rim_after_generation(self, ascii_tmpdir):
        pytest.importorskip("cadquery")

        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.revolve import (
            tracked_revolve,
        )

        rev1_path = Path(ascii_tmpdir) / "postgen_rev1.xbf"

        # ---- Rev1: generate an annular disc WITHOUT any selection. ----
        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        comp = session.ensure_component("disk")
        feat = session.ensure_feature(comp, "n_revolve")

        profile1 = _make_annular_profile(50, 20, 15)
        revolve1 = tracked_revolve(
            profile1, (0, 0, 0), (0, 0, 1), 360,
            scope=TopologyCaptureScope(node_id="n_revolve", component_id="disk"),
        )
        writer.write_batch(revolve1.batch)

        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(rev1_path)
        session.close()

        # ---- Post-generation: reopen and create a selection on the rim. ----
        session_pg = OcafDocumentSession.open(rev1_path)
        create_selection_from_role(
            session_pg, "rim", "disk", "n_revolve", "rim",
            policy=SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )
        session_pg.label_index.save_to_ocaf(session_pg.main_label)
        session_pg.repository.save_to(rev1_path)
        session_pg.close()

        # ---- Rev2: reopen, resize, then solve the post-created selection. ----
        session2 = OcafDocumentSession.open(rev1_path)
        writer2 = TopologyNamingWriter(session2)
        comp2 = session2.ensure_component("disk")
        feat2 = session2.ensure_feature(comp2, "n_revolve")

        prev = session2.get_current_result_shape(feat2)
        assert prev is not None
        profile2 = _make_annular_profile(55, 25, 18)
        revolve2 = tracked_revolve(
            profile2, (0, 0, 0), (0, 0, 1), 360,
            scope=TopologyCaptureScope(node_id="n_revolve", component_id="disk"),
        )
        writer2.write_batch(revolve2.batch, previous_result=prev)

        label_map = collect_tnaming_labels(session2.design_root_label)
        service2 = PersistentSelectionService(session2)
        resolution = service2.solve("rim", label_map)

        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        assert len(resolution.resolved_shapes) == 1
        radius = _face_cylinder_radius(resolution.resolved_shapes[0])
        assert radius == 55.0, f"expected rim radius 55.0, got {radius}"
