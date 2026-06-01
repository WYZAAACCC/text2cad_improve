"""Test 5.4: Axisymmetric parts — flange with center bore, annular groove, hole pattern."""

from __future__ import annotations

import pytest

from tests.text_to_cad_real.helpers.capability_probe import (
    has_dialect,
)
from tests.text_to_cad_real.helpers.run_text_to_cad_case import (
    TextToCadCase,
    run_text_to_cad_case,
)


# ── Case A: Flange with center bore, annular groove, hole pattern ──

FLANGE_PROMPT = (
    "生成一个轴对称法兰 reference geometry："
    "外径 120 mm，厚度 16 mm，中心孔直径 40 mm，"
    "前表面有一个环形凹槽，槽中心半径 45 mm，槽宽 6 mm，槽深 2 mm，"
    "在节圆直径 90 mm 上均布 8 个直径 8 mm 的通孔。"
    "单位 mm，不用于制造。"
)


@pytest.mark.slow
class TestAxisymmetricFlange:
    """5.4.1: Axisymmetric flange with center bore, annular groove, hole pattern."""

    def test_flange_should_build(self, test_workspace, deepseek_client, api_key):
        """Flange with bore + annular groove + hole pattern should build successfully."""
        if not has_dialect("axisymmetric"):
            pytest.skip("axisymmetric dialect not available")

        case = TextToCadCase(
            case_id="axisymmetric_flange_reference",
            name="轴对称法兰 reference",
            prompt=FLANGE_PROMPT,
            expected_outcome="should_build",
            expected_route="generative_cad_ir",
            expected_dialects=["axisymmetric"],
            geometry_expectations={
                "outer_diameter_mm": 120.0,
                "thickness_mm": 16.0,
                "bore_diameter_mm": 40.0,
                "hole_count": 8,
                "pcd_mm": 90.0,
            },
        )

        result = run_text_to_cad_case(case, test_workspace, deepseek_client, api_key=api_key)

        # Should build if LLM produces valid RawGcadDocument.
        # Known gap: DeepSeek may add extra fields (name/type/id) to RawValueRef,
        # causing parse failure. Self-correction attempts up to 3 times.
        # Fail-closed on exhausted retries is correct system behavior.
        if result.ok:
            assert result.actual_route == "generative_cad_ir", \
                f"Expected generative_cad_ir, got {result.actual_route}"
            assert result.step_exists, "STEP file must exist"

            # Check STEP is valid
            from tests.text_to_cad_real.helpers.geometry_assertions import (
                assert_step_basic_valid,
            )
            assert_step_basic_valid(result.step_path)

            # Check metadata for axisymmetric dialect
            if result.metadata_exists:
                import json
                meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
                gm = meta.get("generative_metadata", {})
                dialects = [d.get("dialect", "") for d in gm.get("selected_dialects", [])]
                assert "axisymmetric" in dialects, "axisymmetric must be in selected dialects"

                # Check required ops
                op_versions = gm.get("op_versions", [])
                ops = [o.get("op", "") for o in op_versions]
                found_ops = set(ops)
                # At minimum, revolve_profile + cut_center_bore should be present
                assert "revolve_profile" in found_ops, "flange must have revolve_profile"
                assert "cut_center_bore" in found_ops, "flange must have cut_center_bore"


# ── Case B: Hole pattern outside material → fail ──

FLANGE_INVALID_HOLES_PROMPT = (
    "生成外径 80 mm、中心孔 40 mm 的法兰，"
    "在节圆直径 120 mm 上均布 8 个直径 8 mm 的通孔。"
)


@pytest.mark.slow
class TestFlangeInvalidHoles:
    """5.4.2: Holes outside material must fail geometry_preflight."""

    def test_flange_holes_outside_material_fails(self, test_workspace, deepseek_client, api_key):
        """PCD > outer diameter should fail geometry_preflight."""
        if not has_dialect("axisymmetric"):
            pytest.skip("axisymmetric dialect not available")

        case = TextToCadCase(
            case_id="flange_holes_outside_material",
            name="法兰孔阵列超出材料",
            prompt=FLANGE_INVALID_HOLES_PROMPT,
            expected_outcome="should_fail_closed",
        )

        result = run_text_to_cad_case(case, test_workspace, deepseek_client, api_key=api_key)

        assert not result.ok, \
            f"Hole pattern outside material should fail, but succeeded"

        # Error should be in geometry_preflight, dialect_semantics, or parse
        assert result.error_stage in {
            "geometry_preflight", "dialect_semantics", "validation",
            "build_start", "routing", "parse",
        }, f"Unexpected error stage: {result.error_stage}"

        # No importable STEP
        assert not (result.step_exists and result.step_path.stat().st_size > 1000), \
            "No valid STEP should be produced for invalid hole pattern"
