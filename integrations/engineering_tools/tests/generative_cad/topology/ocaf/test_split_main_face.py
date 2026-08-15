"""Split (1→N) main-face selection via split_strategy."""

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


class TestSplitMainFace:
    def test_largest_area_split_strategy(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
            tracked_cut,
        )

        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        box = cq.Workplane("XY").box(40, 40, 10).val()
        face = box.faces(">Z")
        comp = session.ensure_component("comp")
        feat = session.ensure_feature(comp, "n_box")
        writer.write_feature_result(feat, box.wrapped)
        svc = PersistentSelectionService(session)
        svc.create(
            "top", face.wrapped, box.wrapped,
            SelectionPolicy(
                entity_kind=TopologyEntityKind.FACE,
                split_strategy="largest_area",
            ),
        )

        # cut a slot through the middle, splitting the top face
        tool = cq.Workplane("XY").transformed(offset=(0, 0, -2)).box(5, 40, 14).val()
        cut = tracked_cut(
            box, tool, scope=TopologyCaptureScope(node_id="n_cut", component_id="comp"),
        )
        writer.write_batch(cut.batch)

        label_map = collect_tnaming_labels(session.design_root_label)
        resolution = svc.solve("top", label_map)
        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        assert len(resolution.resolved_shapes) == 1

    def test_no_split_strategy_stays_ambiguous(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
            tracked_cut,
        )

        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        box = cq.Workplane("XY").box(40, 40, 10).val()
        face = box.faces(">Z")
        comp = session.ensure_component("comp")
        feat = session.ensure_feature(comp, "n_box")
        writer.write_feature_result(feat, box.wrapped)
        svc = PersistentSelectionService(session)
        svc.create(
            "top", face.wrapped, box.wrapped,
            SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )
        tool = cq.Workplane("XY").transformed(offset=(0, 0, -2)).box(5, 40, 14).val()
        cut = tracked_cut(
            box, tool, scope=TopologyCaptureScope(node_id="n_cut", component_id="comp"),
        )
        writer.write_batch(cut.batch)
        label_map = collect_tnaming_labels(session.design_root_label)
        resolution = svc.solve("top", label_map)
        assert resolution.status in (
            SelectionResolutionStatus.AMBIGUOUS,
            SelectionResolutionStatus.SET,
        )
