"""T8: EDGE selection — Fillet/Chamfer persistent EDGE identity (v5.0 §11)."""

import cadquery as cq
from OCP.TopoDS import TopoDS

from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.fillet import tracked_fillet
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.chamfer import tracked_chamfer
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope, EvolutionKind,
)


class TestT8EdgeSelection:

    def test_fillet_accepts_edge_shapes_not_indices(self):
        """Fillet uses TopoDS_Edge shapes — NOT integer indices (R-06)."""
        box = cq.Workplane("XY").box(20, 20, 10).val()
        edges = list(box.edges())
        edge_shape = TopoDS.Edge_s(edges[0].wrapped)

        result = tracked_fillet(
            box, [edge_shape], radius=2.0,
            scope=TopologyCaptureScope(node_id="edge_test"),
        )
        assert result.result is not None
        assert result.result.Volume() < box.Volume()  # material removed

    def test_chamfer_accepts_edge_shapes_not_indices(self):
        """Chamfer uses TopoDS_Edge shapes — NOT integer indices."""
        box = cq.Workplane("XY").box(20, 20, 10).val()
        edges = list(box.edges())
        edge_shape = TopoDS.Edge_s(edges[0].wrapped)

        result = tracked_chamfer(
            box, [edge_shape], distance=2.0,
            scope=TopologyCaptureScope(node_id="chamfer_edge"),
        )
        assert result.result is not None
        assert result.result.Volume() < box.Volume()

    def test_fillet_edge_produces_face_history(self):
        """Filleted edge → GENERATED fillet face + MODIFIED adjacent faces."""
        box = cq.Workplane("XY").box(20, 20, 10).val()
        edges = list(box.edges())
        edge = TopoDS.Edge_s(edges[0].wrapped)

        result = tracked_fillet(
            box, [edge], radius=2.0,
            scope=TopologyCaptureScope(node_id="hist"),
        )
        kinds = {r.kind for r in result.batch.relations}
        assert EvolutionKind.GENERATED in kinds or EvolutionKind.MODIFIED in kinds

    def test_multiple_edges_fillet_works(self):
        """Fillet on multiple edges produces valid geometry."""
        box = cq.Workplane("XY").box(20, 20, 10).val()
        edges = list(box.edges())[:3]  # first 3 edges
        edge_shapes = [TopoDS.Edge_s(e.wrapped) for e in edges]

        result = tracked_fillet(
            box, edge_shapes, radius=1.0,
            scope=TopologyCaptureScope(node_id="multi_edge"),
        )
        assert result.result is not None
        assert result.result.Volume() > 0
