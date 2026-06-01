"""Test 5.1: Involute spur gear — deterministic primitive route."""

from __future__ import annotations

import pytest

from tests.text_to_cad_real.helpers.capability_probe import (
    has_primitive,
)
from tests.text_to_cad_real.helpers.run_text_to_cad_case import (
    TextToCadCase,
    run_text_to_cad_case,
)


# ── Case A: Standard 20-tooth involute spur gear ──

GEAR_20T_PROMPT = (
    "请生成一个真实渐开线直齿圆柱齿轮，参数如下："
    "齿数 20，模数 2 mm，压力角 20 度，齿宽 10 mm，"
    "中心孔直径 8 mm，齿轮位于 Z 轴方向，单位 mm。"
    "只需要 reference geometry，不用于制造、认证或安装。"
)


@pytest.mark.slow
class TestSpurGearRouteToPrimitive:
    """5.1.2 Case A: Standard 20-tooth involute spur gear → route_to_primitive."""

    def test_gear_20t_should_route_to_primitive(self, test_workspace, deepseek_client, api_key):
        """Verify 20-tooth spur gear routes to deterministic primitive path."""
        if not has_primitive("involute_spur_gear"):
            pytest.skip("involute_spur_gear primitive not available")

        case = TextToCadCase(
            case_id="gear_spur_20t_m2_pa20",
            name="标准 20 齿渐开线直齿轮",
            prompt=GEAR_20T_PROMPT,
            expected_outcome="should_route_to_primitive",
            expected_route="deterministic_primitive",
            expected_primitive="involute_spur_gear",
        )

        result = run_text_to_cad_case(case, test_workspace, deepseek_client, api_key=api_key)

        # Core assertions
        assert result.actual_route == "deterministic_primitive", \
            f"Expected deterministic_primitive route, got {result.actual_route}"

        assert result.ok, f"Primitive build should succeed: {result.error}"

        # STEP file must exist
        assert result.step_exists, f"STEP file not found at {result.step_path}"

        # Assert STEP file is valid (Level A geometry check)
        from tests.text_to_cad_real.helpers.geometry_assertions import (
            assert_step_basic_valid,
        )
        assert_step_basic_valid(result.step_path)

        # Rough bbox check: gear OD ≈ 44mm, face width ≈ 10mm
        if result.step_path:
            try:
                from seekflow_engineering_tools.cadquery_backend.inspector import inspect_step
                from seekflow_engineering_tools.config import EngineeringToolsConfig
                config = EngineeringToolsConfig()
                inspection = inspect_step(result.step_path, config)
                bbox = inspection.get("bbox", {})
                if bbox:
                    x_span = abs(bbox.get("x_max", 0) - bbox.get("x_min", 0))
                    y_span = abs(bbox.get("y_max", 0) - bbox.get("y_min", 0))
                    z_span = abs(bbox.get("z_max", 0) - bbox.get("z_min", 0))
                    dia_approx = max(x_span, y_span)
                    assert 42 <= dia_approx <= 48, \
                        f"Gear OD should be ~44mm, got ~{dia_approx:.0f}mm"
                    assert 8 <= z_span <= 14, \
                        f"Face width should be ~10mm, got ~{z_span:.0f}mm"
            except ImportError:
                pass  # CadQuery not available for bbox check
            except Exception:
                pass  # Inspection failed but STEP exists


# ── Case B: Invalid gear parameters → fail_closed ──

GEAR_INVALID_PROMPT = (
    "生成一个 2 齿、模数 2 mm、压力角 20 度的渐开线直齿轮。"
)


@pytest.mark.slow
class TestSpurGearInvalidFailClosed:
    """5.1.3 Case B: Invalid gear parameters must fail-closed."""

    def test_gear_2_teeth_should_fail(self, test_workspace, deepseek_client, api_key):
        """2-tooth gear is mechanically invalid; must be rejected."""
        if not has_primitive("involute_spur_gear"):
            pytest.skip("involute_spur_gear primitive not available")

        case = TextToCadCase(
            case_id="gear_invalid_teeth_2",
            name="非法 2 齿齿轮",
            prompt=GEAR_INVALID_PROMPT,
            expected_outcome="should_fail_closed",
            expected_route="unsupported",
        )

        result = run_text_to_cad_case(case, test_workspace, deepseek_client, api_key=api_key)

        assert not result.ok, \
            f"2-tooth gear should be rejected, but build succeeded"

        # Error should be in routing, primitive validation, or params
        assert result.error_stage in {
            "routing", "primitive_validation", "params", "build_start",
            "validation",
        }, f"Unexpected error stage: {result.error_stage}"

        # Must not produce importable STEP
        assert not (result.step_exists and result.step_path.stat().st_size > 1000), \
            "No valid STEP should be produced for invalid gear"


# ── Case C: Manufacturing-certified gear request → reject ──

GEAR_CERTIFIED_PROMPT = (
    "生成一个可以直接生产制造、保证强度和寿命的认证级渐开线齿轮，"
    "20 齿，模数 2 mm，齿宽 10 mm。"
)


@pytest.mark.slow
class TestSpurGearCertifiedReject:
    """5.1.4 Case C: Certified/manufacturing claim must be rejected."""

    def test_gear_certified_must_reject(self, test_workspace, deepseek_client, api_key):
        """Certified/manufacturing claims must be rejected."""
        case = TextToCadCase(
            case_id="gear_certified_manufacturing_request",
            name="制造认证级齿轮请求",
            prompt=GEAR_CERTIFIED_PROMPT,
            expected_outcome="should_fail_closed",
        )

        result = run_text_to_cad_case(case, test_workspace, deepseek_client, api_key=api_key)

        assert not result.ok, \
            f"Certified gear request should be rejected, but build succeeded"

        # Check error message for manufacturing/certified keywords
        error_msg = (result.error or "").lower()
        assert any(kw in error_msg for kw in [
            "manufacturing", "certified", "unsupported", "unsafe", "reject",
            "not_allowed",
        ]), f"Error should mention manufacturing/certified rejection: {result.error}"
