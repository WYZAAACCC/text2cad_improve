"""PR-6: Multi-tool Boolean + Builder Report — §2.8 tests.

These tests use CadQuery/OCP to build real geometry and verify
that the history-aware multi-tool Boolean wrapper correctly tracks
per-instance face history.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §2.8
"""

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.history_wrappers import (
    BooleanBuilderReport,
    history_aware_boolean_cut,
    history_aware_boolean_fuse,
    history_aware_boolean_multi_tool,
)


# ═══════════════════════════════════════════════════════════════════════════════
# BooleanBuilderReport
# ═══════════════════════════════════════════════════════════════════════════════


class TestBooleanBuilderReport:
    """Verify builder report records algorithm metadata."""

    def test_default_report_values(self):
        report = BooleanBuilderReport()
        assert report.algorithm == "BRepAlgoAPI_Cut"
        assert report.tool_count == 1
        assert report.has_history is False
        assert report.degradation_tier == 1

    def test_multi_tool_report(self):
        report = BooleanBuilderReport(
            algorithm="BRepAlgoAPI_Cut",
            tool_count=60,
            has_history=True,
            occt_version="7.6.0",
            degradation_tier=2,
        )
        assert report.tool_count == 60
        assert report.has_history is True
        assert report.occt_version == "7.6.0"


# ═══════════════════════════════════════════════════════════════════════════════
# Single-tool Boolean with history tracking
# ═══════════════════════════════════════════════════════════════════════════════


class TestSingleToolBooleanHistory:
    """Verify history_aware_boolean_cut/fuse capture OCCT history."""

    def test_cut_captures_history_for_target_and_tool(self):
        """A box cut by a cylinder should track both target and tool faces."""
        box = cq.Workplane("XY").box(20, 20, 20)
        tool = (
            cq.Workplane("XY")
            .transformed(offset=(10, 10, 0))
            .circle(5)
            .extrude(20)
        )

        target_faces = box.faces().vals()
        tool_faces = tool.faces().vals()

        result = history_aware_boolean_cut(
            box.val().wrapped,
            tool.val().wrapped,
            input_target_faces=[f.wrapped for f in target_faces[:6]],
            input_tool_faces=[f.wrapped for f in tool_faces[:3]],
        )
        assert result is not None, "Cut should succeed"
        assert result.result_shape is not None
        assert result.history is not None

    def test_fuse_returns_result_for_valid_input(self):
        """Two overlapping boxes should fuse successfully."""
        a = cq.Workplane("XY").box(10, 10, 10)
        b = cq.Workplane("XY").transformed(offset=(5, 5, 0)).box(10, 10, 10)

        result = history_aware_boolean_fuse(
            a.val().wrapped,
            b.val().wrapped,
        )
        assert result is not None, "Fuse should succeed"


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-tool Boolean — §2.8
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultiToolBoolean:
    """Verify history_aware_boolean_multi_tool tracks per-instance history."""

    def test_multi_tool_cut_with_two_cutters(self):
        """Two separate cutters on one target should each be tracked."""
        target = cq.Workplane("XY").box(30, 30, 10)

        cutter1 = (
            cq.Workplane("XY")
            .transformed(offset=(-5, 0, 0))
            .circle(3)
            .extrude(10)
        )
        cutter2 = (
            cq.Workplane("XY")
            .transformed(offset=(5, 0, 0))
            .circle(3)
            .extrude(10)
        )

        target_faces = target.faces().vals()
        c1_faces = cutter1.faces().vals()
        c2_faces = cutter2.faces().vals()

        result = history_aware_boolean_multi_tool(
            target.val().wrapped,
            [cutter1.val().wrapped, cutter2.val().wrapped],
            input_target_faces=[f.wrapped for f in target_faces[:6]],
            input_tool_faces_by_uid={
                "cutter_0": [f.wrapped for f in c1_faces[:3]],
                "cutter_1": [f.wrapped for f in c2_faces[:3]],
            },
            operation="cut",
        )
        assert result is not None, "Multi-tool cut should succeed"
        assert result.result_shape is not None
        assert result.builder_report is not None
        report = result.builder_report
        assert report["tool_count"] == 2

    def test_multi_tool_empty_tools_returns_none(self):
        """Empty tool list should return None."""
        target = cq.Workplane("XY").box(10, 10, 10)
        result = history_aware_boolean_multi_tool(
            target.val().wrapped,
            [],
            operation="cut",
        )
        assert result is None

    def test_multi_tool_generated_faces_grouped_by_tool_uid(self):
        """Generated faces should be keyed by tool UID."""
        target = cq.Workplane("XY").box(20, 20, 10)
        cutter = (
            cq.Workplane("XY")
            .transformed(offset=(0, 0, 0))
            .circle(4)
            .extrude(10)
        )

        c_faces = cutter.faces().vals()
        result = history_aware_boolean_multi_tool(
            target.val().wrapped,
            [cutter.val().wrapped],
            input_tool_faces_by_uid={
                "slot_017": [f.wrapped for f in c_faces[:3]],
            },
            operation="cut",
        )
        assert result is not None
        # Check that generated_faces keys contain the tool UID
        gen_keys = list(result.generated_faces.keys())
        assert any("slot_017" in k for k in gen_keys), (
            f"Generated face keys should include tool UID 'slot_017', "
            f"got: {gen_keys}"
        )
