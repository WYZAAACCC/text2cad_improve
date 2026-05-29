"""Test GenerativeCADSpec Pydantic schema validation."""

import pytest

from seekflow_engineering_tools.generative_cad.ir import (
    FeatureGraph,
    FeatureGraphNode,
    GenerativeCADSpec,
    SafetyFlags,
    SelectedBase,
    SystemValidationContract,
)


def _make_minimal_spec(**overrides):
    """Build a minimal valid GenerativeCADSpec."""
    data = {
        "part_name": "test_disk",
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
    return data


class TestGenerativeCADSpec:
    def test_minimal_valid_spec(self):
        spec = GenerativeCADSpec.model_validate(_make_minimal_spec())
        assert spec.part_name == "test_disk"
        assert spec.ir_version == "g_cad_ir_v0.1"
        assert spec.trust_level == "reference_geometry"
        assert len(spec.selected_bases) == 1
        assert spec.selected_bases[0].base_id == "axisymmetric_base"

    def test_missing_selected_bases_fails(self):
        data = _make_minimal_spec()
        data["selected_bases"] = []
        with pytest.raises(ValueError, match="selected_bases"):
            GenerativeCADSpec.model_validate(data)

    def test_node_base_not_in_selected_bases_fails(self):
        data = _make_minimal_spec()
        data["selected_bases"] = [{"base_id": "sketch_extrude_base", "base_version": "0.1.0"}]
        with pytest.raises(ValueError, match="not present in selected_bases"):
            GenerativeCADSpec.model_validate(data)

    def test_safety_flag_false_fails(self):
        data = _make_minimal_spec()
        data["safety"] = {
            "non_flight_reference_only": False,
            "not_airworthy": True,
            "not_certified": True,
            "not_for_manufacturing": True,
            "not_for_installation": True,
            "no_structural_validation": True,
            "no_life_prediction": True,
        }
        with pytest.raises(ValueError, match="must be true"):
            GenerativeCADSpec.model_validate(data)

    def test_require_step_file_false_fails(self):
        data = _make_minimal_spec()
        data["system_validation_contract"] = {
            "require_step_file": False,
            "require_metadata_sidecar": True,
            "require_closed_solid": True,
        }
        with pytest.raises(ValueError, match="require_step_file cannot be false"):
            GenerativeCADSpec.model_validate(data)

    def test_require_metadata_sidecar_false_fails(self):
        data = _make_minimal_spec()
        data["system_validation_contract"] = {
            "require_step_file": True,
            "require_metadata_sidecar": False,
            "require_closed_solid": True,
        }
        with pytest.raises(ValueError, match="require_metadata_sidecar cannot be false"):
            GenerativeCADSpec.model_validate(data)

    def test_require_closed_solid_false_fails(self):
        data = _make_minimal_spec()
        data["system_validation_contract"] = {
            "require_step_file": True,
            "require_metadata_sidecar": True,
            "require_closed_solid": False,
        }
        with pytest.raises(ValueError, match="require_closed_solid cannot be false"):
            GenerativeCADSpec.model_validate(data)

    def test_extra_unknown_field_fails(self):
        data = _make_minimal_spec()
        data["unknown_field"] = "should_fail"
        with pytest.raises(ValueError):
            GenerativeCADSpec.model_validate(data)

    def test_trust_level_cannot_exceed_reference_geometry(self):
        data = _make_minimal_spec()
        data["trust_level"] = "manufacturing_ready"
        with pytest.raises(ValueError, match="trust_level"):
            GenerativeCADSpec.model_validate(data)

    def test_part_name_empty_fails(self):
        data = _make_minimal_spec()
        data["part_name"] = "   "
        with pytest.raises(ValueError, match="part_name"):
            GenerativeCADSpec.model_validate(data)

    def test_all_safety_flags_default_to_true(self):
        spec = GenerativeCADSpec.model_validate(_make_minimal_spec())
        s = spec.safety
        assert s.non_flight_reference_only is True
        assert s.not_airworthy is True
        assert s.not_certified is True
        assert s.not_for_manufacturing is True
        assert s.not_for_installation is True
        assert s.no_structural_validation is True
        assert s.no_life_prediction is True


class TestFeatureGraphNode:
    def test_empty_id_fails(self):
        with pytest.raises(ValueError, match="node id"):
            FeatureGraphNode(
                id="  ",
                base_id="axisymmetric_base",
                op="revolve_profile",
                phase="base_solid",
            )

    def test_empty_base_id_fails(self):
        with pytest.raises(ValueError, match="base_id"):
            FeatureGraphNode(
                id="n1",
                base_id="  ",
                op="revolve_profile",
                phase="base_solid",
            )

    def test_empty_op_fails(self):
        with pytest.raises(ValueError, match="op"):
            FeatureGraphNode(
                id="n1",
                base_id="axisymmetric_base",
                op="  ",
                phase="base_solid",
            )

    def test_required_with_may_skip_fails(self):
        with pytest.raises(ValueError, match="required nodes"):
            FeatureGraphNode(
                id="n1",
                base_id="axisymmetric_base",
                op="revolve_profile",
                phase="base_solid",
                required=True,
                degradation_policy="may_skip_with_warning",
            )

    def test_optional_with_may_skip_ok(self):
        node = FeatureGraphNode(
            id="n1",
            base_id="axisymmetric_base",
            op="revolve_profile",
            phase="base_solid",
            required=False,
            degradation_policy="may_skip_with_warning",
        )
        assert node.required is False


class TestFeatureGraph:
    def test_duplicate_node_ids_fails(self):
        with pytest.raises(ValueError, match="unique"):
            FeatureGraph(
                nodes=[
                    FeatureGraphNode(
                        id="same", base_id="axisymmetric_base",
                        op="revolve_profile", phase="base_solid",
                    ),
                    FeatureGraphNode(
                        id="same", base_id="axisymmetric_base",
                        op="cut_center_bore", phase="primary_cut",
                        params={"diameter_mm": 10, "axis": "Z"},
                    ),
                ]
            )


class TestSystemValidationContract:
    def test_invalid_bbox_length_fails(self):
        with pytest.raises(ValueError, match="expected_bbox_mm"):
            SystemValidationContract(expected_bbox_mm=[1.0, 2.0])


class TestSafetyFlags:
    def test_all_fields_default_true(self):
        s = SafetyFlags()
        d = s.model_dump()
        for k, v in d.items():
            assert v is True, f"Safety flag {k} should be True, got {v}"

    def test_all_must_be_true(self):
        for field in SafetyFlags.model_fields:
            data = {
                "non_flight_reference_only": True,
                "not_airworthy": True,
                "not_certified": True,
                "not_for_manufacturing": True,
                "not_for_installation": True,
                "no_structural_validation": True,
                "no_life_prediction": True,
            }
            data[field] = False
            with pytest.raises(ValueError, match="must be true"):
                SafetyFlags.model_validate(data)
