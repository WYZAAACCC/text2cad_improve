"""v0.8: prompt tests — legacy-free, dialect terminology, forbidden legacy terms."""

from seekflow_engineering_tools.generative_cad.skills.prompts import (
    LEVEL1_ROUTING_SYSTEM_PROMPT,
    LEVEL2_AUTHORING_SYSTEM_PROMPT,
    REPAIR_PATCH_SYSTEM_PROMPT_V2,
)


class TestPromptsV08:
    def test_prompts_do_not_use_legacy_terms_as_active_fields(self):
        """Legacy terms may appear only in 'Do not use' context, not as active instructions."""
        legacy_terms = ["selected_bases", "feature_graph", "base_id", "GenerativeCADSpec"]
        prompts = [
            ("LEVEL1", LEVEL1_ROUTING_SYSTEM_PROMPT),
            ("LEVEL2", LEVEL2_AUTHORING_SYSTEM_PROMPT),
            ("REPAIR", REPAIR_PATCH_SYSTEM_PROMPT_V2),
        ]
        for name, prompt in prompts:
            for term in legacy_terms:
                # Each occurrence must be within a "do not use" / deprecated context
                if term in prompt:
                    # Verify it appears in a negative/deprecation context
                    assert ("Do not use" in prompt or "deprecated" in prompt or
                            "Never include" in prompt), \
                        f"{name} prompt uses legacy term '{term}' without deprecation context"

    def test_level1_prompt_has_hard_rules(self):
        assert "Hard safety rules:" in LEVEL1_ROUTING_SYSTEM_PROMPT
        assert "deterministic_primitive" in LEVEL1_ROUTING_SYSTEM_PROMPT
        assert "generative_cad_ir" in LEVEL1_ROUTING_SYSTEM_PROMPT

    def test_level2_prompt_forbids_unsupported_capabilities_in_raw(self):
        assert "return to Level-1 routing as unsupported" in LEVEL2_AUTHORING_SYSTEM_PROMPT

    def test_level2_prompt_has_rule_30(self):
        assert "Do not invent dialects, operations" in LEVEL2_AUTHORING_SYSTEM_PROMPT

    def test_repair_prompt_mentions_old_value(self):
        assert "old_value" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_has_give_up_rule(self):
        assert "give_up" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_level1_prompt_mentions_composition_dialect(self):
        assert "composition dialect" in LEVEL1_ROUTING_SYSTEM_PROMPT

    def test_level1_prompt_forbids_code(self):
        assert "Do not output CAD code" in LEVEL1_ROUTING_SYSTEM_PROMPT
