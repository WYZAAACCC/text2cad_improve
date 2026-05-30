"""v0.9: repair release tests — give_up, old_value, forbidden paths."""


class TestRepairRelease:
    def _raw_doc(self):
        return {
            "nodes": [
                {"id": "n_holes", "params": {"hole_dia_mm": 32}},
                {"id": "n_body", "params": {}},
            ],
            "components": [{"id": "c1", "owner_dialect": "axisymmetric", "root_node": "n_body"}],
        }

    def test_repair_patch_give_up_accepts_empty_changes(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, apply_repair_patch_v2,
        )
        raw = self._raw_doc()
        patch = RepairPatchV2(give_up=True, changes=[], reason="same error repeated")
        updated = apply_repair_patch_v2(raw, patch)
        assert updated == raw
        assert updated is not raw

    def test_repair_patch_old_value_none_skips_stale_check(self):
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
                    reason="repair",
                )
            ],
            reason="repair",
        )
        updated = apply_repair_patch_v2(raw, patch)
        node = next(n for n in updated["nodes"] if n["id"] == "n_holes")
        assert node["params"]["hole_dia_mm"] == 24

    def test_repair_patch_rejects_selected_dialects_change(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, validate_repair_patch_v2,
        )
        patch = RepairPatchV2(
            changes=[
                RepairChange(
                    path="/selected_dialects",
                    old_value=None,
                    new_value=[],
                    reason="bad",
                )
            ],
            reason="bad",
        )
        ok, issues = validate_repair_patch_v2(patch)
        assert not ok
        assert any(i["code"] == "forbidden_repair_path" for i in issues)

    def test_repair_patch_applied_count_ok_after_all_changes(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, apply_repair_patch_v2,
        )
        raw = self._raw_doc()
        patch = RepairPatchV2(
            target_node="n_body",
            changes=[
                RepairChange(
                    path="/nodes/n_body/degradation_policy",
                    new_value="may_skip_with_warning", reason="test",
                )
            ],
            reason="test",
        )
        updated = apply_repair_patch_v2(raw, patch)
        node = next(n for n in updated["nodes"] if n["id"] == "n_body")
        assert node["degradation_policy"] == "may_skip_with_warning"
