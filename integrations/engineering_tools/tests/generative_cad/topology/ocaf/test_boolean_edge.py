"""Boolean edge capture and edge-selection survival across a cut."""

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyEntityKind,
)


def _edge_length(edge):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS

    props = GProp_GProps()
    BRepGProp.LinearProperties_s(TopoDS.Edge_s(edge), props)
    return round(float(props.Mass()), 3)


class TestBooleanEdge:
    def test_cut_captures_edge_relations(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
            tracked_cut,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            TopologyCaptureScope,
        )

        box = cq.Workplane("XY").box(40, 40, 10).val()
        tool = cq.Workplane("XY").box(5, 40, 20).val()
        tracked = tracked_cut(
            box, tool, scope=TopologyCaptureScope(node_id="n_cut", component_id="comp")
        )

        edge_rels = [
            r for r in tracked.batch.relations
            if r.entity_kind == TopologyEntityKind.EDGE
        ]
        assert len(edge_rels) > 0
        assert tracked.batch.history_complete is True

    def test_edge_selection_survives_non_consuming_cut(self):
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
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
            tracked_cut,
        )

        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        box = cq.Workplane("XY").box(40, 40, 10).val()
        edge = list(box.edges(">Z"))[0]
        comp = session.ensure_component("comp")
        feat = session.ensure_feature(comp, "n_box")
        writer.write_feature_result(feat, box.wrapped)

        svc = PersistentSelectionService(session)
        svc.create(
            "top_edge", edge.wrapped, box.wrapped,
            SelectionPolicy(entity_kind=TopologyEntityKind.EDGE),
        )

        # A centered hole does not touch the outer top edge.
        tool = cq.Workplane("XY").cylinder(5, 10).val()
        cut = tracked_cut(
            box, tool, scope=TopologyCaptureScope(node_id="n_cut", component_id="comp")
        )
        writer.write_batch(cut.batch)

        label_map = collect_tnaming_labels(session.design_root_label)
        resolution = svc.solve("top_edge", label_map)
        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        assert len(resolution.resolved_shapes) == 1
        assert _edge_length(resolution.resolved_shapes[0]) == 40.0
