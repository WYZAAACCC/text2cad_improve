"""Test repair governor — deterministic stop conditions and forbidden patches."""

import pytest

from seekflow_engineering_tools.generative_cad.ir import (
    FeatureGraph,
    FeatureGraphNode,
    GenerativeCADSpec,
    SelectedBase,
)
from seekflow_engineering_tools.generative_cad.repair_governor import (
    RepairPatch,
    RepairState,
    apply_repair_patch,
    can_repair,
    check_forbidden_modifications,
    update_repair_state,
)


def _make_spec(**overrides):
    data = {
        "part_name": "test",
        "selected_bases": [
            {"base_id": "axisymmetric_base", "base_version": "0.1.0"}
        ],
        "feature_graph": {
            "nodes": [
                {
                    "id": "n1",
                    "base_id": "axisymmetric_base",
                    "op": "revolve_profile",
                    "phase": "base_solid",
                    "params": {
                        "axis": "Z",
                        "profile_stations": [
                            {"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 10},
                            {"r_mm": 30, "z_front_mm": 10, "z_rear_mm": 20},
                        ],
                    },
                }
            ]
        },
    }
    data.update(overrides)
    return GenerativeCADSpec.model_validate(data)


class TestCanRepair:
    def test_max_attempts_stops(self):
        state = RepairState(attempts=3, max_attempts=3)
        allowed, reason = can_repair(state)
        assert not allowed
        assert "Max" in reason

    def test_below_max_allows(self):
        state = RepairState(attempts=1, max_attempts=3)
        allowed, _ = can_repair(state)
        assert allowed

    def test_repeated_graph_hash_stops(self):
        spec = _make_spec()
        state = RepairState(
            attempts=1,
            graph_hashes=["sha256:abc123"],
        )
        # Force the hash to match by using the same spec twice
        from seekflow_engineering_tools.generative_cad.legacy.repair_governor_v01 import _hash_graph
        gh = _hash_graph(spec)
        state = RepairState(attempts=1, graph_hashes=[gh])
        allowed, reason = can_repair(state, spec=spec)
        assert not allowed
        assert "Graph hash repeated" in reason

    def test_repeated_error_signature_stops(self):
        from seekflow_engineering_tools.generative_cad.legacy.repair_governor_v01 import _hash_error_signature

        issues = [{"code": "error_1"}, {"code": "error_2"}]
        eh = _hash_error_signature(issues)
        state = RepairState(
            attempts=1,
            error_signature_hashes=[eh, eh],
        )
        allowed, reason = can_repair(state, issues=issues)
        assert not allowed
        assert "Same error signature repeated" in reason

    def test_first_occurrence_allows(self):
        state = RepairState(attempts=0)
        issues = [{"code": "new_error"}]
        allowed, _ = can_repair(state, issues=issues)
        assert allowed


class TestApplyRepairPatch:
    def test_patch_node_params_accepted(self):
        spec = _make_spec()
        patch = RepairPatch(
            target_node="n1",
            changes=[
                {"path": "params", "value": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 60, "z_front_mm": 0, "z_rear_mm": 10},
                        {"r_mm": 40, "z_front_mm": 10, "z_rear_mm": 20},
                    ],
                }},
            ],
            reason="Adjusted radii for better clearance.",
        )
        updated, error = apply_repair_patch(spec, patch)
        assert error == ""
        assert updated is not None
        node = next(n for n in updated.feature_graph.nodes if n.id == "n1")
        assert node.params["profile_stations"][0]["r_mm"] == 60

    def test_patch_depends_on_accepted(self):
        spec = _make_spec(part_name="test_dep")
        patch = RepairPatch(
            target_node="n1",
            changes=[{"path": "depends_on", "value": ["n0"]}],
            reason="Add dependency.",
        )
        updated, error = apply_repair_patch(spec, patch)
        assert error == ""
        node = next(n for n in updated.feature_graph.nodes if n.id == "n1")
        assert "n0" in node.depends_on

    def test_patch_unknown_node_returns_error(self):
        spec = _make_spec()
        patch = RepairPatch(
            target_node="nonexistent",
            changes=[{"path": "params", "value": {}}],
            reason="test",
        )
        _, error = apply_repair_patch(spec, patch)
        assert "not found" in error

    def test_patch_forbidden_path_returns_error(self):
        spec = _make_spec()
        patch = RepairPatch(
            target_node="n1",
            changes=[{"path": "forbidden_field", "value": "bad"}],
            reason="test",
        )
        _, error = apply_repair_patch(spec, patch)
        assert "not in allowed repair scope" in error


class TestForbiddenModifications:
    def test_safety_modification_rejected(self):
        spec_before = _make_spec()
        # Bypass validation via model_copy to simulate forbidden modification
        spec_dict = spec_before.model_dump()
        spec_dict["safety"]["not_for_manufacturing"] = False
        # Use model_construct to bypass validation
        spec_after = GenerativeCADSpec.model_construct(**spec_dict)
        issues = check_forbidden_modifications(spec_before, spec_after)
        assert len(issues) > 0

    def test_selected_bases_modification_rejected(self):
        spec_before = _make_spec()
        # Bypass validation via model_copy to simulate forbidden modification
        spec_dict = spec_before.model_dump()
        spec_dict["selected_bases"] = [
            {"base_id": "sketch_extrude_base", "base_version": "0.1.0"}
        ]
        # Also fix the node base_id so it's consistent
        spec_dict["feature_graph"]["nodes"][0]["base_id"] = "sketch_extrude_base"
        spec_after = GenerativeCADSpec.model_construct(**spec_dict)
        issues = check_forbidden_modifications(spec_before, spec_after)
        assert len(issues) > 0


class TestUpdateRepairState:
    def test_increments_attempts(self):
        spec = _make_spec()
        state = RepairState()
        updated = update_repair_state(state, spec)
        assert updated.attempts == 1

    def test_records_graph_hash(self):
        spec = _make_spec()
        state = RepairState()
        updated = update_repair_state(state, spec)
        assert len(updated.graph_hashes) == 1

    def test_records_error_signature(self):
        spec = _make_spec()
        state = RepairState()
        updated = update_repair_state(state, spec, issues=[{"code": "test_error"}])
        assert len(updated.error_signature_hashes) == 1
