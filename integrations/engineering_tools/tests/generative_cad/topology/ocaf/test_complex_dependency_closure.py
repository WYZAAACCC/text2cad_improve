"""Complex scenario C: mid-stream feature dependency closure.

A component built as extrude A -> extrude B -> fuse. A face produced by the
middle feature (B's top face) must resolve its owning feature via
_resolve_feature_for_shape (not the terminal feature) and still solve uniquely
after persistence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from seekflow_engineering_tools.generative_cad.pipeline.run import (
    _resolve_feature_for_shape,
)
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.topology.ocaf.capture_session import (
    CaptureSession,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.complex_harness import (
    ComplexModelHarness,
    SelectionExpectation,
    face_area,
    shape_summary,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionPolicy,
    TopologyCaptureScope,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_fuse,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
    tracked_extrude,
)


def _stage_extrude(capture, width, depth, height, x_offset, node_id):
    import cadquery as cq

    profile = (
        cq.Workplane("XY")
        .transformed(offset=(x_offset, 0, 0))
        .rect(width, depth)
        .val()
    )
    tracked = tracked_extrude(
        profile, (0, 0, height),
        scope=TopologyCaptureScope(node_id=node_id, component_id="comp"),
    )
    capture.stage(tracked.batch)
    return tracked


def _b_top_face(body):
    """Return B's top face: centroid near (25, 0, 10), area ~100."""
    for f in body.Faces():
        c = f.Center()
        if abs(c.x - 25.0) < 1.0 and abs(c.z - 10.0) < 1.0:
            a = face_area(f.wrapped)
            if a is not None and abs(a - 100.0) < 2.0:
                return f.wrapped
    return None


def _make_capture_ctx():
    ctx = RuntimeContext(
        out_step=Path("out.step"),
        metadata_path=Path("meta.json"),
        workspace_root=Path("."),
    )
    ctx.capture_session = CaptureSession()

    _stage_extrude(ctx.capture_session, 20, 20, 10, 0.0, "n_first")
    tracked_b = _stage_extrude(ctx.capture_session, 10, 10, 10, 25.0, "n_second")
    fused = tracked_fuse(
        tracked_b.result, _stage_extrude(
            ctx.capture_session, 20, 20, 10, 0.0, "n_dummy",
        ).result,
        scope=TopologyCaptureScope(node_id="n_third", component_id="comp"),
    )
    ctx.capture_session.stage(fused.batch)
    return ctx, fused.result


class TestComplexDependencyClosure:
    def test_midstream_face_resolves_to_producer_feature(self):
        pytest.importorskip("cadquery")
        ctx, body = _make_capture_ctx()
        b_top = _b_top_face(body)
        assert b_top is not None, "B top face not found"
        node = _resolve_feature_for_shape(ctx, "comp", b_top)
        assert node == "n_second", f"expected n_second, got {node!r}"

    def test_midstream_selection_solves_unique_across_revision(self, ascii_tmpdir):
        pytest.importorskip("cadquery")
        import cadquery as cq

        xbf1 = Path(ascii_tmpdir) / "closure_rev1.xbf"
        h = ComplexModelHarness("comp")
        h.new_session(revision=1)

        a = tracked_extrude(
            cq.Workplane("XY").rect(20, 20).val(), (0, 0, 10),
            scope=TopologyCaptureScope(node_id="n_first", component_id="comp"),
        )
        h.write_feature("n_first", a.batch)
        b = tracked_extrude(
            cq.Workplane("XY").transformed(offset=(25, 0, 0)).rect(10, 10).val(),
            (0, 0, 10),
            scope=TopologyCaptureScope(node_id="n_second", component_id="comp"),
        )
        h.write_feature("n_second", b.batch)
        fused = tracked_fuse(
            a.result, b.result,
            scope=TopologyCaptureScope(node_id="n_third", component_id="comp"),
        )
        h.write_feature("n_third", fused.batch)

        b_top = _b_top_face(fused.result)
        assert b_top is not None
        h.create_selection(
            "b_top", b_top, fused.result.wrapped,
            SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )
        h.save(xbf1)

        h.open_session(xbf1)
        outcomes = h.solve_and_check([
            SelectionExpectation(
                "b_top", status="unique", count=1,
                area_range=(99.0, 101.0), label="B top",
            ),
        ])
        for exp, ok, detail in outcomes:
            assert ok, detail
        assert h.monitor.report()["passed"]
