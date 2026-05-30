"""v0.9: prompt path precision — verify repair prompt uses <node_id>/<component_id> placeholders."""

from seekflow_engineering_tools.generative_cad.skills.prompts import REPAIR_PATCH_SYSTEM_PROMPT_V2


class TestPromptPaths:
    def test_repair_prompt_uses_placeholder_paths(self):
        assert "/nodes/<node_id>/params/<field>" in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/components/<component_id>/root_node" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_no_ambiguous_double_slash(self):
        assert "/nodes//params/" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/components//root_node" not in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_mentions_old_value(self):
        assert "old_value" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_mentions_give_up(self):
        assert "give_up" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_output_json_only(self):
        assert "Output JSON only" in REPAIR_PATCH_SYSTEM_PROMPT_V2
