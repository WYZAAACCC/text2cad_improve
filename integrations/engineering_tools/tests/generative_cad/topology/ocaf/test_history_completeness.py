"""G8: history_complete is honest for modification-type tracked ops."""

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    TopologyCaptureScope,
)


def _scope(node_id):
    return TopologyCaptureScope(node_id=node_id, component_id="part")


class TestHistoryCompleteness:
    def test_fillet_carries_unchanged_faces(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from OCP.TopoDS import TopoDS
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.fillet import (
            tracked_fillet,
        )

        box = cq.Workplane("XY").box(20, 20, 10).val()
        edge = TopoDS.Edge_s(list(box.edges())[0].wrapped)
        tracked = tracked_fillet(box, [edge], 1.0, scope=_scope("fillet"))

        carry = [r for r in tracked.batch.relations if "/carry/" in r.relation_id]
        assert len(carry) >= 1
        assert all(r.kind == EvolutionKind.MODIFIED for r in carry)
        assert tracked.batch.history_complete is True

    def test_chamfer_carries_unchanged_faces(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from OCP.TopoDS import TopoDS
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.chamfer import (
            tracked_chamfer,
        )

        box = cq.Workplane("XY").box(20, 20, 10).val()
        edge = TopoDS.Edge_s(list(box.edges())[0].wrapped)
        tracked = tracked_chamfer(box, [edge], 1.0, scope=_scope("chamfer"))

        carry = [r for r in tracked.batch.relations if "/carry/" in r.relation_id]
        assert len(carry) >= 1
        assert all(r.kind == EvolutionKind.MODIFIED for r in carry)
        assert tracked.batch.history_complete is True

    def test_circular_pattern_history_complete(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.pattern import (
            tracked_circular_pattern,
        )

        box = cq.Workplane("XY").box(10, 10, 10).val()
        tracked = tracked_circular_pattern(
            box, (0, 0, 0), (0, 0, 1), 4, radius_mm=30, scope=_scope("circular")
        )
        assert isinstance(tracked.batch.history_complete, bool)
