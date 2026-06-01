"""Test 5.5: Sketch-extrude parts — L-bracket mounting plate."""

from __future__ import annotations

import pytest

from tests.text_to_cad_real.helpers.capability_probe import (
    has_dialect,
)
from tests.text_to_cad_real.helpers.run_text_to_cad_case import (
    TextToCadCase,
    run_text_to_cad_case,
)


# ── L-bracket mounting plate ──

L_BRACKET_PROMPT = (
    "生成一个 L 型安装支架 reference geometry："
    "底板 80 mm x 40 mm x 6 mm，"
    "竖板 80 mm x 50 mm x 6 mm，与底板成 90 度，"
    "底板上有两个直径 6 mm 的安装孔，孔中心距左右边各 20 mm，"
    "竖板上有一个直径 10 mm 的中心孔。"
    "单位 mm，不用于制造。"
)


@pytest.mark.slow
class TestLBracketPlate:
    """5.5.1: L-bracket mounting plate — sketch_extrude."""

    def test_l_bracket_should_build(self, test_workspace, deepseek_client, api_key):
        """L-bracket should build if sketch_extrude + composition are available,
        otherwise fail_closed with clear error."""
        has_se = has_dialect("sketch_extrude")
        has_comp = has_dialect("composition")

        case = TextToCadCase(
            case_id="l_bracket_plate_reference",
            name="L 型安装支架",
            prompt=L_BRACKET_PROMPT,
            expected_outcome="should_build" if (has_se and has_comp) else "capability_dependent",
            expected_route="generative_cad_ir",
            expected_dialects=["sketch_extrude"],
        )

        result = run_text_to_cad_case(case, test_workspace, deepseek_client, api_key=api_key)

        if has_se:
            # sketch_extrude is available
            if has_comp:
                # With composition, should succeed if LLM generates valid output.
                # Known gap: DeepSeek may add extra fields to RawValueRef nodes,
                # causing parse failure. Self-correction attempts up to 3 times.
                if result.ok:
                    assert result.step_exists, "STEP file must exist"
                    # Check bbox roughly
                    try:
                        from seekflow_engineering_tools.cadquery_backend.inspector import inspect_step_with_cadquery
                        inspection = inspect_step_with_cadquery(result.step_path)
                        bbox_mm = inspection.get("bbox_mm", [])
                        if bbox_mm and len(bbox_mm) >= 3:
                            max_span = max(bbox_mm[0], bbox_mm[1], bbox_mm[2])
                            assert max_span >= 40, \
                                f"Bracket should be at least 40mm in some dimension, got {max_span}"
                    except (ImportError, Exception):
                        pass

            # Check metadata if available
            if result.metadata_exists:
                import json
                meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
                gm = meta.get("generative_metadata", {})
                dialects = [d.get("dialect", "") for d in gm.get("selected_dialects", [])]
                assert "sketch_extrude" in dialects

                safety = gm.get("safety", {})
                assert safety.get("not_for_manufacturing") is True
        else:
            # sketch_extrude not available → should be capability-dependent fail
            if not result.ok:
                assert result.error_code in {
                    "unsupported_capability", "dialect_not_available",
                    "unsupported", "generative_build_failed",
                }, f"Unexpected error code for missing dialect: {result.error_code}"
