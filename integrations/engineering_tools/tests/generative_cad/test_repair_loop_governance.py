"""Tests for repair loop governance — patch restrictions, forbidden paths, stop conditions."""
import pytest


class TestRepairPatchRestrictions:
    def test_repair_rejects_safety_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            is_forbidden_repair_path,
        )
        assert is_forbidden_repair_path("/safety/non_flight_reference_only")
        assert is_forbidden_repair_path("/safety")

    def test_repair_rejects_schema_version_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            is_forbidden_repair_path,
        )
        assert is_forbidden_repair_path("/schema_version")

    def test_repair_rejects_selected_dialects_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            is_forbidden_repair_path,
        )
        assert is_forbidden_repair_path("/selected_dialects")
        assert is_forbidden_repair_path("/selected_dialects/0/dialect")

    def test_repair_rejects_constraint_flag_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            is_forbidden_repair_path,
        )
        assert is_forbidden_repair_path("/constraints/require_step_file")
        assert is_forbidden_repair_path("/constraints/require_closed_solid")

    def test_repair_rejects_dialect_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            is_forbidden_repair_path,
        )
        assert is_forbidden_repair_path("/nodes/n1/dialect")

    def test_repair_rejects_op_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            is_forbidden_repair_path,
        )
        assert is_forbidden_repair_path("/nodes/n1/op")

    def test_repair_rejects_op_version_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            is_forbidden_repair_path,
        )
        assert is_forbidden_repair_path("/nodes/n1/op_version")

    def test_repair_rejects_owner_dialect_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            is_forbidden_repair_path,
        )
        assert is_forbidden_repair_path("/components/main/owner_dialect")

    def test_repair_allows_param_patch(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            is_forbidden_repair_path,
            is_allowed_repair_path,
        )
        path = "/nodes/n_holes/params/pcd_mm"
        assert not is_forbidden_repair_path(path)
        assert is_allowed_repair_path(path)

    def test_repair_allows_inputs_patch(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            is_forbidden_repair_path,
            is_allowed_repair_path,
        )
        path = "/nodes/n_cut/inputs"
        assert not is_forbidden_repair_path(path)
        assert is_allowed_repair_path(path)

    def test_repair_allows_outputs_patch(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            is_forbidden_repair_path,
            is_allowed_repair_path,
        )
        path = "/nodes/n_revolve/outputs"
        assert not is_forbidden_repair_path(path)
        assert is_allowed_repair_path(path)

    def test_repair_allows_root_node_patch(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            is_forbidden_repair_path,
            is_allowed_repair_path,
        )
        path = "/components/main_disk/root_node"
        assert not is_forbidden_repair_path(path)
        assert is_allowed_repair_path(path)


class TestRepairPatchApply:
    def test_apply_param_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2,
            RepairChange,
            apply_repair_patch_v2,
        )

        raw = {
            "nodes": [
                {"id": "n1", "params": {"width_mm": 100.0}}
            ]
        }
        patch = RepairPatchV2(
            target_node="n1",
            changes=[
                RepairChange(
                    path="/nodes/n1/params/width_mm",
                    old_value=100.0,
                    new_value=200.0,
                    reason="Correct width",
                )
            ],
            reason="Fix dimension",
        )
        updated = apply_repair_patch_v2(raw, patch)
        assert updated["nodes"][0]["params"]["width_mm"] == 200.0

    def test_apply_rejects_old_value_mismatch(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2,
            RepairChange,
            apply_repair_patch_v2,
        )

        raw = {
            "nodes": [
                {"id": "n1", "params": {"width_mm": 100.0}}
            ]
        }
        patch = RepairPatchV2(
            target_node="n1",
            changes=[
                RepairChange(
                    path="/nodes/n1/params/width_mm",
                    old_value=999.0,  # wrong old value
                    new_value=200.0,
                    reason="Fix dimension",
                )
            ],
            reason="Fix dimension",
        )
        with pytest.raises(ValueError, match="old_value mismatch"):
            apply_repair_patch_v2(raw, patch)

    def test_apply_rejects_forbidden_path(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2,
            RepairChange,
            apply_repair_patch_v2,
        )

        raw = {"safety": {"non_flight_reference_only": True}}
        patch = RepairPatchV2(
            changes=[
                RepairChange(
                    path="/safety/non_flight_reference_only",
                    old_value=True,
                    new_value=False,
                    reason="Disable safety",
                )
            ],
            reason="Bad patch",
        )
        with pytest.raises(ValueError, match="invalid repair patch"):
            apply_repair_patch_v2(raw, patch)

    def test_give_up_patch_returns_unchanged(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2,
            apply_repair_patch_v2,
        )
        import copy

        raw = {"nodes": [{"id": "n1", "params": {"x": 1}}]}
        original = copy.deepcopy(raw)
        patch = RepairPatchV2(
            changes=[],
            reason="Cannot fix",
            give_up=True,
        )
        updated = apply_repair_patch_v2(raw, patch)
        assert updated == original
