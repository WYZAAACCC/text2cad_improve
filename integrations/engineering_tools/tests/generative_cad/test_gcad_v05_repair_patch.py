"""v0.5 repair patch tests — path validation, forbidden paths, apply logic."""

import pytest


class TestRepairPatchValidation:
    def test_repair_patch_rejects_safety_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, validate_repair_patch_v2,
        )
        patch = RepairPatchV2(
            changes=[RepairChange(path="/safety/not_certified", new_value=False, reason="bad")],
            reason="bad",
        )
        ok, issues = validate_repair_patch_v2(patch)
        assert not ok
        assert any(i["code"] == "forbidden_repair_path" for i in issues)

    def test_repair_patch_rejects_node_op_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, validate_repair_patch_v2,
        )
        patch = RepairPatchV2(
            target_node="n1",
            changes=[RepairChange(path="/nodes/n1/op", new_value="fake_op", reason="bad")],
            reason="bad",
        )
        ok, issues = validate_repair_patch_v2(patch)
        assert not ok

    def test_repair_patch_allows_node_param_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, validate_repair_patch_v2,
        )
        patch = RepairPatchV2(
            target_node="n_holes",
            changes=[
                RepairChange(
                    path="/nodes/n_holes/params/hole_dia_mm",
                    old_value=32, new_value=24, reason="reduce hole diameter",
                )
            ],
            reason="preflight failed",
        )
        ok, issues = validate_repair_patch_v2(patch)
        assert ok

    def test_apply_repair_patch_updates_target_node_param_only(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, apply_repair_patch_v2,
        )
        raw = {
            "nodes": [
                {"id": "n1", "params": {"r_mm": 100}},
                {"id": "n2", "params": {"hole_dia_mm": 32}},
            ]
        }
        patch = RepairPatchV2(
            target_node="n2",
            changes=[RepairChange(
                path="/nodes/n2/params/hole_dia_mm", old_value=32, new_value=24,
                reason="reduce",
            )],
            reason="preflight",
        )
        updated = apply_repair_patch_v2(raw, patch)
        assert updated["nodes"][1]["params"]["hole_dia_mm"] == 24
        # n1 unchanged
        assert updated["nodes"][0]["params"]["r_mm"] == 100

    def test_repair_patch_rejects_empty_changes(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, validate_repair_patch_v2,
        )
        patch = RepairPatchV2(changes=[], reason="empty")
        ok, issues = validate_repair_patch_v2(patch)
        assert not ok
        assert any(i["code"] == "empty_repair_patch" for i in issues)

    def test_give_up_passes_validation(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, validate_repair_patch_v2,
        )
        patch = RepairPatchV2(changes=[], reason="cannot fix", give_up=True)
        ok, _ = validate_repair_patch_v2(patch)
        assert ok
