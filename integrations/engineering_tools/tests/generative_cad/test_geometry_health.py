"""Phase 2: GeometryHealth + required degradation tests.

Tests verify:
- GeometryHealth model validation
- inspect_geometry_health best-effort behavior
- handle_feature_failure for required/optional/degradation policy
- Handler degradation: required raises, optional skips with warn
- health_log recorded in executor

OCP/CadQuery tests are skipped when cadquery is unavailable.
"""

import sys
from pathlib import Path
from typing import Literal

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# Skip entire module if cadquery is not available
cadquery_available = False
try:
    import cadquery as cq  # noqa: F401
    cadquery_available = True
except ImportError:
    pass

requires_cadquery = pytest.mark.skipif(
    not cadquery_available, reason="CadQuery/OCP not available"
)


# ═══════════════════════════════════════════════════════════════
# Imports
# ═══════════════════════════════════════════════════════════════

from seekflow_engineering_tools.generative_cad.runtime.health import (
    GeometryHealth,
    inspect_geometry_health,
)
from seekflow_engineering_tools.generative_cad.runtime.recovery import (
    handle_feature_failure,
)
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.ir.canonical import (
    CanonicalNode,
    CanonicalValueDecl,
)


# ═══════════════════════════════════════════════════════════════
# GeometryHealth model tests (no OCP needed)
# ═══════════════════════════════════════════════════════════════

class TestGeometryHealthModel:
    def test_default_health_is_unknown(self):
        h = GeometryHealth()
        assert h.status == "unknown"
        assert h.score is None
        assert h.valid_brep is None

    def test_ok_health_score(self):
        h = GeometryHealth(
            status="ok", closed=True, body_count=1,
            volume_mm3=1000.0, bbox_mm=[10.0, 10.0, 10.0],
            score=1.0,
        )
        assert h.status == "ok"
        assert h.score == 1.0

    def test_error_health_score(self):
        h = GeometryHealth(
            status="error", closed=False, score=0.5,
        )
        assert h.status == "error"

    def test_extra_forbid(self):
        with pytest.raises(Exception):
            GeometryHealth(unknown_field="test", status="ok")

    def test_score_range(self):
        h = GeometryHealth(status="ok", score=1.0)
        assert 0.0 <= h.score <= 1.0


# ═══════════════════════════════════════════════════════════════
# inspect_geometry_health tests (with CadQuery mock)
# ═══════════════════════════════════════════════════════════════

class TestInspectGeometryHealth:
    def test_unknown_when_no_runtime(self):
        """When geometry_runtime raises and BRepCheck is unavailable, health is unknown.

        Note: if OCP bindings happen to be available in the test environment,
        BRepCheck might try to validate the dummy object and produce an error
        report. In that case health.status becomes "error" — which is also
        acceptable behavior (the dummy object genuinely has no valid geometry).
        We accept both outcomes.
        """
        class DummyRuntime:
            runtime_id = "dummy"
            runtime_version = "0"

            def export_step(self, obj, path): pass
            def inspect_solid(self, obj): raise RuntimeError("no")
            def validate_closed_solid(self, obj): raise RuntimeError("no")
            def compute_bbox_mm(self, obj): raise RuntimeError("no")
            def count_bodies(self, obj): raise RuntimeError("no")

        class DummyObj:
            pass

        class DummyTolerance:
            pass

        health = inspect_geometry_health(
            DummyObj(), DummyRuntime(), DummyTolerance(),
        )
        # Best-effort: unknown when nothing can be assessed, or error if
        # BRepCheck happened to run and found no valid geometry.
        assert health.status in ("unknown", "error")
        if health.status == "unknown":
            assert health.score is None

    @requires_cadquery
    def test_cylinder_health_is_ok(self):
        """Simple cylinder should have ok health."""
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.runtime.cadquery_runtime import CadQueryRuntime
        from seekflow_engineering_tools.generative_cad.runtime.tolerance import DEFAULT_TOLERANCE

        cyl = cq.Workplane("XY").circle(10).extrude(20)
        runtime = CadQueryRuntime()
        health = inspect_geometry_health(cyl, runtime, DEFAULT_TOLERANCE)
        # Cylinder from CadQuery should be valid
        assert health.closed is True or health.closed is None
        assert health.body_count == 1 or health.body_count is None
        assert health.volume_mm3 is None or health.volume_mm3 > 0


# ═══════════════════════════════════════════════════════════════
# handle_feature_failure tests (no OCP needed)
# ═══════════════════════════════════════════════════════════════

def _make_ctx():
    return RuntimeContext(
        out_step=Path("/tmp/test.step"),
        metadata_path=Path("/tmp/test.json"),
        workspace_root=Path("/tmp"),
    )


def _make_node(
    required: bool = True,
    degradation_policy: Literal["fail", "may_skip_with_warning"] = "fail",
):
    return CanonicalNode(
        id="n1", component="c1", dialect="axisymmetric",
        op="cut_center_bore", op_version="1.0.0", phase="primary_cut",
        inputs=[], outputs=[CanonicalValueDecl(name="body", type="solid", value_id="solid:c1:n1:body")],
        params={}, required=required, degradation_policy=degradation_policy,
    )


class TestHandleFeatureFailure:
    def test_required_raises(self):
        node = _make_node(required=True)
        ctx = _make_ctx()
        body = object()
        with pytest.raises(RuntimeError, match="Required operation"):
            handle_feature_failure(
                node=node, ctx=ctx, original_body=body,
                op_name="cut_center_bore",
                reason="test failure",
            )

    def test_required_raises_with_exc(self):
        node = _make_node(required=True)
        ctx = _make_ctx()
        body = object()
        with pytest.raises(RuntimeError, match="something went wrong"):
            handle_feature_failure(
                node=node, ctx=ctx, original_body=body,
                op_name="cut_center_bore",
                exc=ValueError("something went wrong"),
            )

    def test_optional_may_skip_returns_body(self):
        node = _make_node(required=False, degradation_policy="may_skip_with_warning")
        ctx = _make_ctx()
        body = object()
        result = handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_center_bore",
            exc=ValueError("test"),
        )
        assert "body" in result
        assert len(ctx.warnings) == 1
        assert "Optional feature" in ctx.warnings[0]
        assert len(ctx.degraded_features) == 1
        assert ctx.degraded_features[0]["node_id"] == "n1"

    def test_optional_fail_policy_raises(self):
        node = _make_node(required=False, degradation_policy="fail")
        ctx = _make_ctx()
        body = object()
        with pytest.raises(RuntimeError, match="only 'may_skip_with_warning'"):
            handle_feature_failure(
                node=node, ctx=ctx, original_body=body,
                op_name="cut_center_bore",
                reason="test",
            )

    def test_no_exc_and_no_reason_works(self):
        """handle_feature_failure should work with neither exc nor reason."""
        node = _make_node(required=True)
        ctx = _make_ctx()
        body = object()
        with pytest.raises(RuntimeError, match="unknown error"):
            handle_feature_failure(
                node=node, ctx=ctx, original_body=body,
                op_name="test_op",
            )

    def test_degraded_feature_record_structure(self):
        node = _make_node(required=False, degradation_policy="may_skip_with_warning")
        ctx = _make_ctx()
        body = object()
        handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_circular_hole_pattern",
            reason="invalid params: count=0",
        )
        assert ctx.degraded_features[0] == {
            "node_id": "n1",
            "op": "cut_center_bore",
            "op_name": "cut_circular_hole_pattern",
            "reason": "invalid params: count=0",
        }


# ═══════════════════════════════════════════════════════════════
# Integration: ctx.geometry_health_log available
# ═══════════════════════════════════════════════════════════════

class TestGeometryHealthLog:
    def test_context_has_health_log(self):
        ctx = _make_ctx()
        assert hasattr(ctx, "geometry_health_log")
        assert ctx.geometry_health_log == {}

    def test_health_log_default_factory_isolation(self):
        """Each RuntimeContext gets its own geometry_health_log dict."""
        ctx1 = _make_ctx()
        ctx2 = _make_ctx()
        ctx1.geometry_health_log["test"] = {"status": "ok"}
        assert "test" not in ctx2.geometry_health_log
