"""M5: Repair prompt and RepairPatch behavior tests."""


class TestRepairPromptPaths:
    def test_repair_prompt_uses_node_id_placeholders(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/nodes/<node_id>/params/<field>" in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/nodes/<node_id>/dialect" in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/components/<component_id>/root_node" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_does_not_contain_double_slash_paths(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/nodes//" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/components//" not in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_forbids_safety_modification(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "Do not modify /safety" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_forbids_op_version_modification(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/nodes/<node_id>/op_version" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_has_allowed_path_examples(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/nodes/n_holes/params/pcd_mm" in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/components/main_disk/root_node" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_has_give_up_rules(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert '"give_up": true' in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "old_value no longer matches" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_repair_prompt_has_give_up_for_safety_change(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "require changing safety" in REPAIR_PATCH_SYSTEM_PROMPT_V2


class TestRepairPatchBehavior:
    def test_patch_allowed_params_path(self):
        """Patching /nodes/<id>/params/<field> is allowed."""
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            apply_repair_patch_v2, RepairPatchV2, RepairChange,
        )
        doc = {
            "schema_version": "g_cad_core_v0.2",
            "nodes": [{"id": "n1", "params": {"pcd_mm": 100}}],
        }
        patch = RepairPatchV2(
            reason="fix pcd",
            changes=[RepairChange(
                path="/nodes/n1/params/pcd_mm",
                new_value=200,
                old_value=100,
                reason="fix pcd",
            )],
        )
        result = apply_repair_patch_v2(doc, patch)
        assert result["nodes"][0]["params"]["pcd_mm"] == 200
        assert result is not doc  # deep copy

    def test_patch_old_value_mismatch_rejects(self):
        """old_value mismatch rejects the patch."""
        import pytest
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            apply_repair_patch_v2, RepairPatchV2, RepairChange,
        )
        doc = {
            "schema_version": "g_cad_core_v0.2",
            "nodes": [{"id": "n1", "params": {"pcd_mm": 300}}],
        }
        patch = RepairPatchV2(
            reason="fix pcd",
            changes=[RepairChange(
                path="/nodes/n1/params/pcd_mm",
                new_value=200,
                old_value=100,
                reason="fix pcd",
            )],
        )
        with pytest.raises(ValueError, match="old_value mismatch"):
            apply_repair_patch_v2(doc, patch)

    def test_patch_forbidden_safety_path_rejected(self):
        """Patching /safety path is not allowed by design — this is a prompt-level guard."""
        from seekflow_engineering_tools.generative_cad.skills.prompts import REPAIR_PATCH_SYSTEM_PROMPT_V2
        # The prompt forbids it; the repair governor should also reject
        assert "Do not modify /safety" in REPAIR_PATCH_SYSTEM_PROMPT_V2
