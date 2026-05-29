"""v0.6: repair patch missing target error tests."""

import pytest


class TestRepairPatchMissingTarget:
    def _raw_doc(self):
        return {
            "nodes": [{"id": "n1", "params": {"r_mm": 100}}],
            "components": [{"id": "c1", "owner_dialect": "axisymmetric", "root_node": "n1"}],
        }

    def test_apply_repair_patch_rejects_missing_node(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, apply_repair_patch_v2,
        )
        patch = RepairPatchV2(
            target_node="missing",
            changes=[
                RepairChange(
                    path="/nodes/missing/params/hole_dia_mm",
                    new_value=10, reason="test",
                )
            ],
            reason="test",
        )
        with pytest.raises(ValueError, match="repair target node not found"):
            apply_repair_patch_v2(self._raw_doc(), patch)

    def test_apply_repair_patch_rejects_missing_component(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, apply_repair_patch_v2,
        )
        patch = RepairPatchV2(
            changes=[
                RepairChange(
                    path="/components/missing/root_node",
                    new_value="n1", reason="test",
                )
            ],
            reason="test",
        )
        with pytest.raises(ValueError, match="repair target component not found"):
            apply_repair_patch_v2(self._raw_doc(), patch)

    def test_llm_validation_hints_requires_dict(self):
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2, RepairChange, apply_repair_patch_v2,
        )
        patch = RepairPatchV2(
            changes=[
                RepairChange(
                    path="/llm_validation_hints",
                    new_value="not_a_dict", reason="test",
                )
            ],
            reason="test",
        )
        with pytest.raises(ValueError, match="must be dict"):
            apply_repair_patch_v2(self._raw_doc(), patch)
