"""v0.5 skills schema invariants and prompt hardening tests."""

import pytest


class TestDialectSelectionPlan:
    def test_generative_route_requires_dialects(self):
        from seekflow_engineering_tools.generative_cad.skills.schemas import DialectSelectionPlan
        with pytest.raises(ValueError):
            DialectSelectionPlan(route_decision="generative_cad_ir", selected_dialects=[])

    def test_unsupported_route_requires_unsupported_capabilities(self):
        from seekflow_engineering_tools.generative_cad.skills.schemas import DialectSelectionPlan
        with pytest.raises(ValueError):
            DialectSelectionPlan(route_decision="unsupported", unsupported_capabilities=[])

    def test_deterministic_primitive_rejects_dialects(self):
        from seekflow_engineering_tools.generative_cad.skills.schemas import (
            DialectSelectionPlan, DialectSelectionItem,
        )
        with pytest.raises(ValueError):
            DialectSelectionPlan(
                route_decision="deterministic_primitive",
                selected_dialects=[DialectSelectionItem(dialect="axisymmetric", version="0.2.0", reason="test")],
            )

    def test_duplicate_dialect_rejected(self):
        from seekflow_engineering_tools.generative_cad.skills.schemas import (
            DialectSelectionPlan, DialectSelectionItem,
        )
        with pytest.raises(ValueError):
            DialectSelectionPlan(
                route_decision="generative_cad_ir",
                selected_dialects=[
                    DialectSelectionItem(dialect="axisymmetric", version="0.2.0", reason="a"),
                    DialectSelectionItem(dialect="axisymmetric", version="0.2.0", reason="b"),
                ],
            )

    def test_validate_against_catalog_rejects_unknown_dialect(self):
        from seekflow_engineering_tools.generative_cad.skills.schemas import (
            DialectSelectionPlan, DialectSelectionItem,
            validate_selection_plan_against_catalog,
        )
        plan = DialectSelectionPlan(
            route_decision="generative_cad_ir",
            selected_dialects=[DialectSelectionItem(dialect="nonexistent", version="0.2.0", reason="test")],
        )
        catalog = {"dialects": [{"dialect_id": "axisymmetric"}, {"dialect_id": "sketch_extrude"}]}
        ok, issues = validate_selection_plan_against_catalog(plan, catalog)
        assert not ok
        assert any(i["code"] == "unknown_selected_dialect" for i in issues)


class TestPromptHardening:
    def test_level2_prompt_does_not_suggest_unsupported_capabilities_in_raw(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
        assert "output a JSON object with unsupported_capabilities" not in LEVEL2_AUTHORING_SYSTEM_PROMPT

    def test_repair_prompt_has_output_schema(self):
        from seekflow_engineering_tools.generative_cad.skills.orchestrator import build_repair_prompt_v2
        prompt = build_repair_prompt_v2({}, {"issues": []}, {})
        assert "output_schema" in prompt
