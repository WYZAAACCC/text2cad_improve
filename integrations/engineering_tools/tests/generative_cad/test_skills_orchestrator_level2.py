"""Tests for orchestrator Level-2 auto-loading usage skills from BasePackages."""
import pytest


class TestLevel2AutoLoad:
    def test_level2_prompt_auto_loads_usage_skill(self):
        from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
            build_level2_authoring_prompt,
        )
        from seekflow_engineering_tools.generative_cad.skills.schemas import (
            DialectSelectionPlan,
            DialectSelectionItem,
        )

        plan = DialectSelectionPlan(
            route_decision="generative_cad_ir",
            selected_dialects=[
                DialectSelectionItem(dialect="axisymmetric", version="0.2.0", reason="test"),
            ],
        )

        prompt = build_level2_authoring_prompt(
            user_request="Create a washer",
            selection_plan=plan,
        )

        # usage_skills should be auto-populated (not empty)
        assert "usage_skills" in prompt
        assert prompt["usage_skills"], "usage_skills should be auto-populated"
        assert "axisymmetric" in prompt["usage_skills"], (
            "axisymmetric usage skill should be auto-loaded"
        )

    def test_level2_prompt_fails_when_selected_dialect_has_no_base_package(self):
        from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
            build_level2_authoring_prompt,
        )
        from seekflow_engineering_tools.generative_cad.skills.schemas import (
            DialectSelectionPlan,
            DialectSelectionItem,
        )

        plan = DialectSelectionPlan(
            route_decision="generative_cad_ir",
            selected_dialects=[
                DialectSelectionItem(
                    dialect="nonexistent_dialect_xyz",
                    version="0.2.0",
                    reason="test",
                ),
            ],
        )

        with pytest.raises(ValueError, match="no registered BasePackage"):
            build_level2_authoring_prompt(
                user_request="Test",
                selection_plan=plan,
                strict_usage_skill=True,
            )

    def test_level2_prompt_non_strict_does_not_fail(self):
        from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
            build_level2_authoring_prompt,
        )
        from seekflow_engineering_tools.generative_cad.skills.schemas import (
            DialectSelectionPlan,
            DialectSelectionItem,
        )

        plan = DialectSelectionPlan(
            route_decision="generative_cad_ir",
            selected_dialects=[
                DialectSelectionItem(
                    dialect="nonexistent_dialect_xyz",
                    version="0.2.0",
                    reason="test",
                ),
            ],
        )

        # Non-strict mode: should not raise, just not load the skill
        prompt = build_level2_authoring_prompt(
            user_request="Test",
            selection_plan=plan,
            strict_usage_skill=False,
        )
        assert prompt["usage_skills"] == {}

    def test_level2_prompt_accepts_explicit_usage_skills(self):
        from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
            build_level2_authoring_prompt,
        )
        from seekflow_engineering_tools.generative_cad.skills.schemas import (
            DialectSelectionPlan,
            DialectSelectionItem,
        )

        plan = DialectSelectionPlan(
            route_decision="generative_cad_ir",
            selected_dialects=[
                DialectSelectionItem(dialect="axisymmetric", version="0.2.0", reason="test"),
            ],
        )

        custom_skills = {"axisymmetric": "# Custom usage skill"}
        prompt = build_level2_authoring_prompt(
            user_request="Create a washer",
            selection_plan=plan,
            usage_skills=custom_skills,
        )

        # Should use explicit skills, not auto-generated ones
        assert prompt["usage_skills"] == custom_skills

    def test_level2_prompt_usage_skill_mentions_phase_order(self):
        from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
            build_level2_authoring_prompt,
        )
        from seekflow_engineering_tools.generative_cad.skills.schemas import (
            DialectSelectionPlan,
            DialectSelectionItem,
        )

        plan = DialectSelectionPlan(
            route_decision="generative_cad_ir",
            selected_dialects=[
                DialectSelectionItem(dialect="axisymmetric", version="0.2.0", reason="test"),
            ],
        )

        prompt = build_level2_authoring_prompt(
            user_request="Create a washer",
            selection_plan=plan,
        )

        skill = prompt["usage_skills"]["axisymmetric"]
        assert "## Phase order" in skill
        assert "base_solid" in skill


class TestLevel2UsageSkillNoRunnerSource:
    def test_auto_loaded_skill_has_no_runner_source(self):
        from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
            build_level2_authoring_prompt,
        )
        from seekflow_engineering_tools.generative_cad.skills.schemas import (
            DialectSelectionPlan,
            DialectSelectionItem,
        )

        plan = DialectSelectionPlan(
            route_decision="generative_cad_ir",
            selected_dialects=[
                DialectSelectionItem(dialect="axisymmetric", version="0.2.0", reason="test"),
            ],
        )

        prompt = build_level2_authoring_prompt(
            user_request="Create a washer",
            selection_plan=plan,
        )

        skill = prompt["usage_skills"]["axisymmetric"]
        forbidden = ["import cadquery", "cq.Workplane", "subprocess", "def run_component"]
        for pattern in forbidden:
            assert pattern not in skill, f"auto-loaded skill contains runner source: {pattern!r}"
