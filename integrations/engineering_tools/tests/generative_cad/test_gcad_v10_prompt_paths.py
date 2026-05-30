"""v1.0: prompt path precision — repair prompt uses valid /path notation."""

from seekflow_engineering_tools.generative_cad.skills.prompts import REPAIR_PATCH_SYSTEM_PROMPT_V2


class TestPromptPathsV10:
    def test_repair_prompt_uses_valid_placeholder_paths(self):
        assert "/nodes/<node_id>/params/<field>" in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/components/<component_id>/root_node" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_no_ambiguous_double_slash(self):
        assert "/nodes//params/" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/nodes//inputs" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/components//root_node" not in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_uses_path_notation_for_forbidden_rules(self):
        assert "Do not modify /schema_version." in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "Do not modify /selected_dialects." in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "Do not modify /safety." in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_uses_path_notation_for_node_fields(self):
        assert "/nodes/<node_id>/dialect" in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/nodes/<node_id>/op." in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/nodes/<node_id>/op_version" in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/components/<component_id>/owner_dialect" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_mentions_old_value_and_give_up(self):
        assert "old_value" in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "give_up" in REPAIR_PATCH_SYSTEM_PROMPT_V2
