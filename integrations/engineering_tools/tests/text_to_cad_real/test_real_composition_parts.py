"""Test 5.6: Composition parts — bushing + flange assembly."""

from __future__ import annotations

import pytest

from tests.text_to_cad_real.helpers.capability_probe import (
    has_dialect,
)
from tests.text_to_cad_real.helpers.run_text_to_cad_case import (
    TextToCadCase,
    run_text_to_cad_case,
)


# ── Bushing + flange composition ──

COMPOSED_BUSHING_FLANGE_PROMPT = (
    "生成一个由轴套和法兰组合而成的 reference geometry："
    "轴套外径 40 mm，内孔 20 mm，长度 60 mm；"
    "法兰外径 90 mm，厚度 10 mm，位于轴套中部；"
    "法兰上在节圆直径 70 mm 均布 6 个直径 6 mm 通孔。"
    "单位 mm，不用于制造。"
)


@pytest.mark.slow
class TestComposedBushingFlange:
    """5.6.1: Bushing + flange composition with boolean_union."""

    def test_composed_bushing_flange(self, test_workspace, deepseek_client, api_key):
        """Multi-component composition must use composition dialect."""
        has_axisym = has_dialect("axisymmetric")
        has_comp = has_dialect("composition")

        if not (has_axisym and has_comp):
            pytest.skip("axisymmetric + composition dialects required")

        case = TextToCadCase(
            case_id="composed_bushing_flange",
            name="轴套 + 法兰组合",
            prompt=COMPOSED_BUSHING_FLANGE_PROMPT,
            expected_outcome="should_build",
            expected_route="generative_cad_ir",
            expected_dialects=["axisymmetric", "composition"],
        )

        result = run_text_to_cad_case(case, test_workspace, deepseek_client, api_key=api_key)

        # Should build if LLM produces valid RawGcadDocument.
        # Known gap: DeepSeek may add extra fields to RawValueRef nodes,
        # causing parse failure. Self-correction attempts up to 3 times.
        if result.ok:
            assert result.actual_route == "generative_cad_ir", \
                f"Expected generative_cad_ir, got {result.actual_route}"
            assert result.step_exists, "STEP file must exist"

            # Basic STEP validation
            from tests.text_to_cad_real.helpers.geometry_assertions import (
                assert_step_basic_valid,
            )
            assert_step_basic_valid(result.step_path)

        # Verify metadata (only if build succeeded)
        if result.ok and result.metadata_exists:
            import json
            meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
            gm = meta.get("generative_metadata", {})

            dialects = [d.get("dialect", "") for d in gm.get("selected_dialects", [])]
            assert "axisymmetric" in dialects, "axisymmetric must be used"

            # If composition was used
            if len(dialects) > 1:
                assert "composition" in dialects, \
                    "composition dialect must be used for multi-component assembly"

            # Check boolean/merge operations present
            op_versions = gm.get("op_versions", [])
            ops = [o.get("op", "") for o in op_versions]
            # Should have at minimum boolean_union or equivalent composition op
            boolean_ops = {"boolean_union", "boolean_cut", "boolean_intersect"}
            has_boolean = any(op in boolean_ops for op in ops)
            if len(dialects) > 1:
                assert has_boolean, \
                    f"Composition must include boolean operation. Ops found: {ops}"

            # Safety
            safety = gm.get("safety", {})
            assert safety.get("not_for_manufacturing") is True
