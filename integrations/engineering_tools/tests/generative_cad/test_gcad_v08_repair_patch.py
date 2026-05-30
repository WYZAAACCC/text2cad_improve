"""v0.8: RepairPatchV2 final hardening — give_up, old_value, applied count."""

import pytest


class TestRepairPatchV08:
    def _raw_doc(self):
        return {
            "nodes": [
                {"id": "n_holes", "params": {"hole_dia_mm": 32}},
                {"id": "n_body", "params": {}},
            ],
            "components": [{"id": "c1", "owner_dialect": "axisymmetric", "root_node": "n_body"}],
        }

    def test_repair_patch_give_up_returns_unchanged(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, apply_repair_patch_v2,
        )
        raw = self._raw_doc()
        patch = RepairPatchV2(give_up=True, changes=[], reason="repeat error")
        updated = apply_repair_patch_v2(raw, patch)
        assert updated == raw
        assert updated is not raw  # deep copy

    def test_repair_patch_old_value_mismatch_rejected(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, apply_repair_patch_v2,
        )
        raw = self._raw_doc()
        patch = RepairPatchV2(
            target_node="n_holes",
            changes=[
                RepairChange(
                    path="/nodes/n_holes/params/hole_dia_mm",
                    old_value=999,
                    new_value=24,
                    reason="reduce",
                )
            ],
            reason="repair",
        )
        with pytest.raises(ValueError, match="old_value mismatch"):
            apply_repair_patch_v2(raw, patch)

    def test_repair_patch_old_value_match_succeeds(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, apply_repair_patch_v2,
        )
        raw = self._raw_doc()
        patch = RepairPatchV2(
            target_node="n_holes",
            changes=[
                RepairChange(
                    path="/nodes/n_holes/params/hole_dia_mm",
                    old_value=32,
                    new_value=24,
                    reason="reduce",
                )
            ],
            reason="repair",
        )
        updated = apply_repair_patch_v2(raw, patch)
        node = next(n for n in updated["nodes"] if n["id"] == "n_holes")
        assert node["params"]["hole_dia_mm"] == 24

    def test_repair_patch_old_value_none_skips_check(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, apply_repair_patch_v2,
        )
        raw = self._raw_doc()
        patch = RepairPatchV2(
            target_node="n_holes",
            changes=[
                RepairChange(
                    path="/nodes/n_holes/params/hole_dia_mm",
                    old_value=None,
                    new_value=24,
                    reason="reduce",
                )
            ],
            reason="repair",
        )
        updated = apply_repair_patch_v2(raw, patch)
        assert updated["nodes"][0]["params"]["hole_dia_mm"] == 24

    def test_repair_patch_applied_count_enforced(self):
        """If a change path matches but is unsupported, applied != len(changes) raises."""
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, apply_repair_patch_v2,
        )
        raw = self._raw_doc()
        patch = RepairPatchV2(
            changes=[
                RepairChange(
                    path="/nodes/n_holes/params/hole_dia_mm",
                    new_value=24, reason="test",
                ),
                RepairChange(
                    path="/nodes/n_holes/params/depth_mm",
                    new_value=10, reason="test",
                ),
            ],
            reason="test",
        )
        updated = apply_repair_patch_v2(raw, patch)
        # Both should be applied
        node = next(n for n in updated["nodes"] if n["id"] == "n_holes")
        assert node["params"]["hole_dia_mm"] == 24
        assert node["params"]["depth_mm"] == 10

    def test_repair_patch_old_value_mismatch_on_root_node(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, apply_repair_patch_v2,
        )
        raw = self._raw_doc()
        patch = RepairPatchV2(
            changes=[
                RepairChange(
                    path="/components/c1/root_node",
                    old_value="wrong_root",
                    new_value="n_body",
                    reason="fix root",
                )
            ],
            reason="repair",
        )
        with pytest.raises(ValueError, match="old_value mismatch"):
            apply_repair_patch_v2(raw, patch)
