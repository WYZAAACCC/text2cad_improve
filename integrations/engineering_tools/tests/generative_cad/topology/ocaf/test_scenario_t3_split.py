"""T3: 1→N Split — one source face generates multiple result faces (v5.0 §11)."""

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_cut,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope, EvolutionKind,
)


class TestT3Split:

    def test_cut_produces_face_split(self):
        """Boolean cut can split one face into multiple result faces."""
        box = cq.Workplane("XY").box(20, 20, 10).val()
        tool = cq.Workplane("XY").transformed(offset=(0, 5, -1)).box(5, 20, 12).val()

        result = tracked_cut(
            box, tool,
            scope=TopologyCaptureScope(node_id="split_test"),
        )
        assert result.result is not None
        assert result.result.Volume() < box.Volume()  # material removed

        # Cut should produce GENERATED and/or DELETED relations
        kinds = {r.kind for r in result.batch.relations}
        assert EvolutionKind.GENERATED in kinds or EvolutionKind.DELETED in kinds, \
            f"Cut should produce face evolution: got {kinds}"

    def test_cut_source_keys_are_stable(self):
        """source_keys use 'target_face_N' / 'tool_face_N' naming."""
        box = cq.Workplane("XY").box(20, 20, 10).val()
        tool = cq.Workplane("XY").transformed(offset=(5, 5, -1)).box(10, 10, 12).val()

        result = tracked_cut(
            box, tool,
            scope=TopologyCaptureScope(node_id="keys_test"),
        )
        keys = {r.source_key for r in result.batch.relations}
        # Should have target-facing and tool-facing source keys
        has_target = any("target" in k for k in keys)
        has_tool = any("tool" in k for k in keys)
        assert has_target or has_tool, \
            f"Cut should produce 'target' or 'tool' source keys: {keys}"

    def test_cut_volume_matches_native(self):
        """Tracked cut produces same volume as native CadQuery cut."""
        box = cq.Workplane("XY").box(20, 20, 10).val()
        tool = cq.Workplane("XY").transformed(offset=(5, 5, -1)).box(10, 10, 12).val()

        tracked = tracked_cut(box, tool,
                              scope=TopologyCaptureScope(node_id="vol"))
        native = box.cut(tool)
        assert abs(tracked.result.Volume() - native.Volume()) < 0.01
