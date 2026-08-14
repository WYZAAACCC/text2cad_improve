"""Tier B tracked ops: circular pattern, shell, sweep, loft produce history."""

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import TopologyCaptureScope


def _scope(node_id):
    return TopologyCaptureScope(node_id=node_id, component_id="part")


class TestTierBTrackedOps:
    def test_circular_pattern(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.pattern import (
            tracked_circular_pattern,
        )

        box = cq.Workplane("XY").box(10, 10, 10).val()
        tracked = tracked_circular_pattern(box, (0, 0, 0), (0, 0, 1), 4, radius_mm=30, scope=_scope("cp"))
        assert len(list(tracked.result.Solids())) == 4
        assert len(tracked.batch.relations) > 0

    def test_shell(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.offset_sweep import (
            tracked_shell,
        )

        box = cq.Workplane("XY").box(20, 20, 20).val()
        tracked = tracked_shell(box, 2.0, faces_to_remove=[], scope=_scope("sh"))
        assert tracked.result.Volume() > 0
        assert len(tracked.batch.relations) > 0

    def test_sweep(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from OCP.gp import gp_Pnt
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.offset_sweep import (
            tracked_sweep,
        )

        wb = BRepBuilderAPI_MakeWire()
        wb.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(0, 0, 20)).Edge())
        profile = cq.Workplane("XY").circle(5).wire().val()
        tracked = tracked_sweep(profile, wb.Wire(), scope=_scope("sw"))
        assert tracked.result.Volume() > 0
        assert len(tracked.batch.relations) > 0

    def test_loft(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.offset_sweep import (
            tracked_loft,
        )

        w1 = cq.Workplane("XY").circle(5).wire().val()
        w2 = cq.Workplane("XY").workplane(offset=20).circle(8).wire().val()
        tracked = tracked_loft([w1, w2], scope=_scope("lo"))
        assert tracked.result.Volume() > 0
        assert len(tracked.batch.relations) > 0

    def test_fillet_role(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.fillet import (
            tracked_fillet,
        )

        box = cq.Workplane("XY").box(20, 20, 20)
        edge = box.edges(">Z").val()
        tracked = tracked_fillet(box.val(), [edge.wrapped], 2.0, scope=_scope("f"))
        assert tracked.batch.construction_roles["fillet"] is not None

    def test_chamfer_role(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.chamfer import (
            tracked_chamfer,
        )

        box = cq.Workplane("XY").box(20, 20, 20)
        edge = box.edges(">Z").val()
        tracked = tracked_chamfer(box.val(), [edge.wrapped], 2.0, scope=_scope("c"))
        assert tracked.batch.construction_roles["chamfer"] is not None
