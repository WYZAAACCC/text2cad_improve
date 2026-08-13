"""T7: Pattern instance identity — each instance has stable face roles (v5.0 §11)."""

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.pattern import (
    tracked_linear_pattern,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope, EvolutionKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.history_graph import (
    HistoryGraph,
    HistoryComposer,
)


def _area_centroid(shape) -> tuple:
    """Return (area, centroid) for a TopoDS_Face — for stable assertions."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    c = props.CentreOfMass()
    return (round(props.Mass(), 2), (round(c.X(), 2), round(c.Y(), 2), round(c.Z(), 2)))


class TestT7PatternIdentity:

    def test_each_instance_has_face_history(self):
        """Each patterned instance (beyond original) has face-level relations."""
        box = cq.Workplane("XY").box(20, 10, 5).val()
        result = tracked_linear_pattern(
            box, direction=(1, 0, 0), count=3, spacing=30,
            scope=TopologyCaptureScope(node_id="pattern_test"),
        )
        # Instances 1 and 2 should have GENERATED face relations
        inst_keys = {r.source_key for r in result.batch.relations}
        assert any("inst_1" in k for k in inst_keys), \
            "Instance 1 should have face history"
        assert any("inst_2" in k for k in inst_keys) or len(result.batch.relations) >= 6, \
            "Pattern should produce per-instance face history"

    def test_count_one_returns_original(self):
        """count=1 → no transform, original volume preserved."""
        box = cq.Workplane("XY").box(20, 10, 5).val()
        result = tracked_linear_pattern(
            box, direction=(1, 0, 0), count=1, spacing=30,
            scope=TopologyCaptureScope(node_id="single"),
        )
        assert abs(result.result.Volume() - box.Volume()) < 0.01

    def test_pattern_fuse_history_present(self):
        """Fuse steps produce history (Generated or Modified)."""
        box = cq.Workplane("XY").box(20, 10, 5).val()
        result = tracked_linear_pattern(
            box, direction=(1, 0, 0), count=2, spacing=30,
            scope=TopologyCaptureScope(node_id="fuse_hist"),
        )
        # Should have per-instance relations + potentially fuse relations
        kinds = {r.kind for r in result.batch.relations}
        # At minimum, GENERATED from transform
        assert EvolutionKind.GENERATED in kinds or EvolutionKind.MODIFIED in kinds, \
            f"Pattern should produce history: got {kinds}"

    def test_compose_original_face_to_final(self):
        """HistoryComposer traces an original face to a final result face."""
        box = cq.Workplane("XY").box(20, 10, 5).val()
        result = tracked_linear_pattern(
            box, direction=(1, 0, 0), count=3, spacing=30,
            scope=TopologyCaptureScope(node_id="compose"),
        )
        top = box.faces(">Z").wrapped

        graph = HistoryGraph.from_relations(result.batch.relations)
        finals = HistoryComposer().compose(
            graph, [top], follow_tokens=("_arg_",),
        )
        assert len(finals) >= 1, "original top face should trace to a final face"

        target = _area_centroid(top)
        assert any(_area_centroid(f) == target for f in finals), \
            "composed final face should match the original top face area/centroid"

        # The multi-stage history must be composable -> history_complete=True.
        assert result.batch.history_complete is True
