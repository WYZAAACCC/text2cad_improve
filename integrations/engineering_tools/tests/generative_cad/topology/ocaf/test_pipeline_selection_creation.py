"""T12-a: pipeline-level persistent selection creation from SelectionSpec."""

from pathlib import Path

import cadquery as cq

from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
from seekflow_engineering_tools.generative_cad.topology.ocaf.capture_session import CaptureSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import collect_tnaming_labels
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope,
    LiveEvolutionBatch,
    LiveEvolutionRelation,
    EvolutionKind,
    TopologyEntityKind,
    ProofClass,
    SelectionSpec,
    SelectionPolicy,
    SelectionResolutionStatus,
)
from seekflow_engineering_tools.generative_cad.pipeline.run import _create_selections_from_specs


def _make_box_batch(box, node_id="box", component_id="comp_a"):
    scope = TopologyCaptureScope(node_id=node_id, component_id=component_id)
    rel = LiveEvolutionRelation(
        relation_id=f"{node_id}/0", operation_id=node_id,
        kind=EvolutionKind.PRIMITIVE, entity_kind=TopologyEntityKind.FACE,
        source_key="body", old_shape=None, new_shapes=(box.wrapped,),
        proof=ProofClass.EXACT_CONSTRUCTION,
    )
    return LiveEvolutionBatch(
        scope=scope, builder_kind="Primitive",
        result_shape=box.wrapped, context_shape=box.wrapped, relations=[rel],
    )


class TestPipelineSelectionCreation:

    def test_create_selection_from_spec(self):
        """A SelectionSpec resolves a component face and registers a selection."""
        box = cq.Workplane("XY").box(20, 10, 5).val()

        ctx = RuntimeContext(
            out_step=Path("out.step"),
            metadata_path=Path("meta.json"),
            workspace_root=Path("."),
        )
        ctx.capture_session = CaptureSession()
        ctx.capture_session.stage(_make_box_batch(box))
        handle = ctx.object_store.put_solid(SolidHandle(id="h1"), box)
        ctx.bind_component_output("comp_a", "body", handle.id)

        session = OcafDocumentSession.create()
        # Write the batch first — TNaming_Builder is a prerequisite for Select().
        writer = TopologyNamingWriter(session)
        for batch in ctx.capture_session.iter_batches():
            writer.write_batch(batch)

        spec = SelectionSpec(
            selection_id="top_face",
            component_id="comp_a",
            face_selector=">Z",
            policy=SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )
        svc = _create_selections_from_specs(ctx, session, [spec])

        # The selection must be registered in the StableLabelIndex.
        entry = session.label_index.get_existing(
            "selection", "lineage", "top_face",
        )
        assert entry is not None, "selection should be indexed"

        # And it must be solvable against the captured history.
        label_map = collect_tnaming_labels(session.design_root_label)
        resolution = svc.solve("top_face", label_map)
        assert resolution.status in (
            SelectionResolutionStatus.UNIQUE,
            SelectionResolutionStatus.AMBIGUOUS,
        ), f"Unexpected resolution: {resolution.status}"

    def test_create_edge_selection_from_spec(self):
        """A SelectionSpec with entity_kind=edge resolves and registers an edge."""
        box = cq.Workplane("XY").box(20, 10, 5).val()

        ctx = RuntimeContext(
            out_step=Path("out.step"),
            metadata_path=Path("meta.json"),
            workspace_root=Path("."),
        )
        ctx.capture_session = CaptureSession()
        ctx.capture_session.stage(_make_box_batch(box))
        handle = ctx.object_store.put_solid(SolidHandle(id="h_edge"), box)
        ctx.bind_component_output("comp_a", "body", handle.id)

        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        for batch in ctx.capture_session.iter_batches():
            writer.write_batch(batch)

        spec = SelectionSpec(
            selection_id="top_edges",
            component_id="comp_a",
            edge_selector=">Z",
            policy=SelectionPolicy(entity_kind=TopologyEntityKind.EDGE),
        )
        svc = _create_selections_from_specs(ctx, session, [spec])

        entry = session.label_index.get_existing(
            "selection", "lineage", "top_edges",
        )
        assert entry is not None, "edge selection should be indexed"

        label_map = collect_tnaming_labels(session.design_root_label)
        resolution = svc.solve("top_edges", label_map)
        assert resolution.status in (
            SelectionResolutionStatus.UNIQUE,
            SelectionResolutionStatus.SET,
            SelectionResolutionStatus.AMBIGUOUS,
        ), f"Unexpected resolution: {resolution.status}"

    def test_direct_single_edge_selection_resolves_unique(self):
        """A single TopoDS_Edge anchored via create() solves UNIQUE."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
            PersistentSelectionService,
        )

        box = cq.Workplane("XY").box(20, 10, 5).val()
        edge = list(box.edges(">Z"))[0]

        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        comp = session.ensure_component("comp_a")
        feat = session.ensure_feature(comp, "n_box")
        writer.write_feature_result(feat, box.wrapped)

        svc = PersistentSelectionService(session)
        svc.create(
            "single_edge", edge.wrapped, box.wrapped,
            SelectionPolicy(entity_kind=TopologyEntityKind.EDGE),
        )

        label_map = collect_tnaming_labels(session.design_root_label)
        resolution = svc.solve("single_edge", label_map)
        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        assert len(resolution.resolved_shapes) == 1

    def test_missing_component_warns_not_raises(self):
        """A spec referencing a missing component does not crash the pipeline."""
        box = cq.Workplane("XY").box(10, 10, 10).val()

        ctx = RuntimeContext(
            out_step=Path("out.step"),
            metadata_path=Path("meta.json"),
            workspace_root=Path("."),
        )
        ctx.capture_session = CaptureSession()
        ctx.capture_session.stage(_make_box_batch(box))

        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        for batch in ctx.capture_session.iter_batches():
            writer.write_batch(batch)

        spec = SelectionSpec(
            selection_id="top_face", component_id="missing", face_selector=">Z",
        )
        _create_selections_from_specs(ctx, session, [spec])
        assert any("selection create failed" in w for w in ctx.warnings)
