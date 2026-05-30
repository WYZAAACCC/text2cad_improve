"""M6: Prompt ABI upgrade tests."""


class TestPromptABIVNext:
    def test_level2_prompt_requires_explicit_constraints(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
        assert "constraints object must be explicitly present" in LEVEL2_AUTHORING_SYSTEM_PROMPT
        assert "constraints.require_step_file must be explicitly true" in LEVEL2_AUTHORING_SYSTEM_PROMPT

    def test_level2_prompt_requires_explicit_safety(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
        assert "safety object must be explicitly present" in LEVEL2_AUTHORING_SYSTEM_PROMPT
        assert "Every safety flag must be explicitly present and true" in LEVEL2_AUTHORING_SYSTEM_PROMPT

    def test_level2_prompt_lists_all_safety_flags(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
        for flag in ["non_flight_reference_only", "not_airworthy", "not_certified",
                      "not_for_manufacturing", "not_for_installation",
                      "no_structural_validation", "no_life_prediction"]:
            assert flag in LEVEL2_AUTHORING_SYSTEM_PROMPT

    def test_level2_prompt_forbids_defaults(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
        assert "Do not rely on schema defaults" in LEVEL2_AUTHORING_SYSTEM_PROMPT

    def test_level2_prompt_forbids_deprecated_fields(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
        assert "selected_bases" in LEVEL2_AUTHORING_SYSTEM_PROMPT
        assert "feature_graph" in LEVEL2_AUTHORING_SYSTEM_PROMPT
        assert "GenerativeCADSpec" in LEVEL2_AUTHORING_SYSTEM_PROMPT

    def test_level2_prompt_forbids_manufacturing_claims(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
        assert "Do not claim manufacturing readiness" in LEVEL2_AUTHORING_SYSTEM_PROMPT

    def test_level1_prompt_has_output_shape(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL1_ROUTING_SYSTEM_PROMPT
        assert "Required output shape" in LEVEL1_ROUTING_SYSTEM_PROMPT
        assert "selected_domain_skills" in LEVEL1_ROUTING_SYSTEM_PROMPT
        assert "safety_notes" in LEVEL1_ROUTING_SYSTEM_PROMPT

    def test_level1_prompt_forbids_unregistered_dialects(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL1_ROUTING_SYSTEM_PROMPT
        assert "Never select a dialect that is not listed" in LEVEL1_ROUTING_SYSTEM_PROMPT
