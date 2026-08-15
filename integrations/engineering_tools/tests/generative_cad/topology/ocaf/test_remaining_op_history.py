"""History honesty and face roles for shell/loft/pattern operations."""

from __future__ import annotations

import pytest

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.offset_sweep import (
    tracked_shell,
    tracked_loft,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.pattern import (
    tracked_linear_pattern,
    tracked_circular_pattern,
)


class TestShellHistory:
    def test_shell_populates_face_roles(self):
        pytest.importorskip("cadquery")
        box = cq.Workplane("XY").box(20, 20, 10).val()
        tracked = tracked_shell(
            box,
            1.0,
            scope=TopologyCaptureScope(node_id="shell_node", component_id="comp_a"),
        )
        assert tracked.batch.history_complete is True
        assert tracked.batch.face_roles


class TestLoftHistory:
    def test_loft_populates_face_roles(self):
        pytest.importorskip("cadquery")
        w1 = cq.Workplane("XY").circle(5).wire().val()
        w2 = cq.Workplane("XY").workplane(offset=20).circle(8).wire().val()
        tracked = tracked_loft(
            [w1, w2],
            scope=TopologyCaptureScope(node_id="loft_node", component_id="comp_a"),
        )
        assert tracked.batch.history_complete is True
        assert tracked.batch.face_roles


class TestPatternFaceRoles:
    def test_linear_pattern_populates_face_roles(self):
        pytest.importorskip("cadquery")
        box = cq.Workplane("XY").box(10, 10, 5).val()
        tracked = tracked_linear_pattern(
            box,
            (1, 0, 0),
            3,
            20,
            scope=TopologyCaptureScope(node_id="linear_node", component_id="comp_a"),
        )
        assert tracked.batch.history_complete is True
        assert tracked.batch.face_roles

    def test_circular_pattern_populates_face_roles(self):
        pytest.importorskip("cadquery")
        box = cq.Workplane("XY").box(10, 10, 5).val()
        tracked = tracked_circular_pattern(
            box,
            (0, 0, 0),
            (0, 0, 1),
            4,
            scope=TopologyCaptureScope(node_id="circular_node", component_id="comp_a"),
        )
        assert tracked.batch.history_complete is True
        assert tracked.batch.face_roles
