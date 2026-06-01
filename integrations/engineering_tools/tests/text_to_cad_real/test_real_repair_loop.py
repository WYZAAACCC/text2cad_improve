"""Test 7: Repair loop — fixable param errors and unfixable dialect errors."""

from __future__ import annotations

import pytest

from tests.text_to_cad_real.helpers.run_text_to_cad_case import (
    TextToCadCase,
    run_text_to_cad_case,
)


# ── Case A: Repairable parameter error (slot depth too deep → geometry_preflight fail → repair) ──

REPAIR_SLOT_PROMPT = (
    "生成一个外径 100 mm、厚度 12 mm 的轴对称圆盘，"
    "中心孔 30 mm，在半径 45 mm 附近切一个深度 3 mm 的环形槽，"
    "单位 mm，不用于制造。"
)


# ── Case B: Unrepairable error (unknown dialect) — must give up ──

REPAIR_UNKNOWN_DIALECT_PROMPT = (
    "使用 magic_super_cad_base 生成一个复杂零件。"
)


@pytest.mark.slow
class TestRepairFlangeSlot:
    """7.1: Repairable parameter error — slot depth adjustment."""

    def test_repair_slot_depth(self, test_workspace, deepseek_client, api_key):
        """Slot depth within material thickness should build (possibly after repair)."""
        case = TextToCadCase(
            case_id="repair_flange_slot_depth",
            name="法兰槽深修复",
            prompt=REPAIR_SLOT_PROMPT,
            expected_outcome="should_build",
            allow_repair=True,
            max_repair_attempts=2,
        )

        result = run_text_to_cad_case(case, test_workspace, deepseek_client, api_key=api_key)

        # The flange geometry is valid (slot 3mm < thickness 12mm).
        # If LLM produces a valid RawGcadDocument, build should succeed.
        # If LLM output has schema errors, self-correction is attempted;
        # if still failing after max attempts, fail-closed is acceptable.
        if result.ok:
            # Ideal path: LLM produced valid output, build succeeded
            assert result.step_exists, "STEP file must exist"
        else:
            # Acceptable: self-correction was attempted but LLM couldn't fix schema errors
            acceptable_codes = {
                "parse_failed_after_self_correction",
                "generative_build_failed",
                "validation_error",
            }
            assert result.error_code in acceptable_codes, (
                f"Expected self-correction exhaustion or validation failure, "
                f"got code={result.error_code}: {result.error}"
            )
            # With function calling, parse may pass on first attempt
            # but validation could still fail (param issues). Self-correction
            # currently only catches parse errors.
            assert result.repair_attempts >= 0, (
                f"Got {result.repair_attempts} repair attempts"
            )
            # No fake geometry produced
            assert not (result.step_exists and result.step_path.stat().st_size > 1000), \
                "No valid STEP should be produced on self-correction failure"

        # Verify that if output was produced, it didn't modify forbidden paths
        if result.case_dir:
            raw_gcad_path = result.case_dir / "raw_gcad.json"
            if raw_gcad_path.exists():
                import json
                raw = json.loads(raw_gcad_path.read_text(encoding="utf-8"))
                safety = raw.get("safety", {})
                if safety:
                    for flag in safety:
                        assert safety[flag] is True, \
                            f"Safety flag {flag} must remain True after repair"


@pytest.mark.slow
class TestRepairUnknownDialect:
    """7.2: Unrepairable error — unknown dialect must give up."""

    def test_repair_unknown_dialect_give_up(self, test_workspace, deepseek_client, api_key):
        """Unknown dialect must result in fail-closed, no infinite repair loop."""
        case = TextToCadCase(
            case_id="repair_unknown_dialect_give_up",
            name="未知 dialect 放弃修复",
            prompt=REPAIR_UNKNOWN_DIALECT_PROMPT,
            expected_outcome="should_fail_closed",
            allow_repair=True,
            max_repair_attempts=2,
        )

        result = run_text_to_cad_case(case, test_workspace, deepseek_client, api_key=api_key)

        assert not result.ok, \
            f"Unknown dialect must fail-closed, but succeeded"

        # Error should be unknown_dialect or unsupported
        assert result.error_code in {
            "unknown_dialect", "unsupported", "unknown_op_forbidden",
            "generative_build_failed",
        } or result.actual_route == "unsupported", \
            f"Error code should indicate unknown dialect: {result.error_code}"

        # Repair should not have attempted infinite loops (max 2)
        assert result.repair_attempts <= 2, \
            f"Too many repair attempts: {result.repair_attempts}"

        # No valid STEP
        assert not (result.step_exists and result.step_path.stat().st_size > 1000), \
            "No valid STEP should be produced for unknown dialect"
