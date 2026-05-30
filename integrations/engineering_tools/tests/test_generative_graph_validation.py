"""Test generative CAD graph validation — fail-closed for unknown base/op."""

import os
os.environ["SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS"] = "1"

import pytest

from seekflow_engineering_tools.generative_cad.graph_validation import (
    run_graph_validation,
    validate_base_semantics,
    validate_graph_dag,
    validate_node_ops_exist,
    validate_op_params_schema,
    validate_phase_order,
    validate_selected_bases_exist,
)
from seekflow_engineering_tools.generative_cad.ir import GenerativeCADSpec


def _make_spec(nodes=None, selected_bases=None, **overrides):
    data = {
        "part_name": "test",
        "selected_bases": selected_bases or [
            {"base_id": "axisymmetric_base", "base_version": "0.1.0"}
        ],
        "feature_graph": {"nodes": nodes or [
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
        ]},
        **overrides,
    }
    return GenerativeCADSpec.model_validate(data)


class TestUnknownBase:
    def test_unknown_base_fails(self):
        spec = _make_spec(selected_bases=[
            {"base_id": "nonexistent_base", "base_version": "0.1.0"}
        ], nodes=[
            {
                "id": "n1", "base_id": "nonexistent_base",
                "op": "some_op", "phase": "base_solid",
                "params": {},
            }
        ])
        report = validate_selected_bases_exist(spec)
        assert not report.ok
        assert any("nonexistent_base" in i.message for i in report.issues)


class TestUnknownOp:
    def test_unknown_op_fails(self):
        spec = _make_spec(nodes=[
            {
                "id": "n1",
                "base_id": "axisymmetric_base",
                "op": "nonexistent_op",
                "phase": "base_solid",
                "params": {},
            }
        ])
        report = validate_node_ops_exist(spec)
        assert not report.ok
        assert any("nonexistent_op" in i.message for i in report.issues)

    def test_known_op_passes(self):
        spec = _make_spec()
        report = validate_node_ops_exist(spec)
        assert report.ok


class TestParamsSchema:
    def test_invalid_params_fails(self):
        spec = _make_spec(nodes=[
            {
                "id": "n1",
                "base_id": "axisymmetric_base",
                "op": "revolve_profile",
                "phase": "base_solid",
                "params": {
                    "axis": "INVALID",
                    "profile_stations": [],
                },
            }
        ])
        report = validate_op_params_schema(spec)
        assert not report.ok

    def test_valid_params_passes(self):
        spec = _make_spec()
        report = validate_op_params_schema(spec)
        assert report.ok


class TestPhaseOrder:
    def test_wrong_phase_fails(self):
        spec = _make_spec(nodes=[
            {
                "id": "n1",
                "base_id": "axisymmetric_base",
                "op": "revolve_profile",
                "phase": "wrong_phase",
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 10},
                        {"r_mm": 30, "z_front_mm": 10, "z_rear_mm": 20},
                    ],
                },
            }
        ])
        report = validate_phase_order(spec)
        assert not report.ok

    def test_correct_phase_passes(self):
        spec = _make_spec()
        report = validate_phase_order(spec)
        assert report.ok


class TestGraphDAG:
    def test_missing_dependency_fails(self):
        spec = _make_spec(nodes=[
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
                "depends_on": ["nonexistent_node"],
            }
        ])
        report = validate_graph_dag(spec)
        assert not report.ok
        assert any("does not exist" in i.message for i in report.issues)

    def test_dag_cycle_fails(self):
        spec = _make_spec(nodes=[
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
                "depends_on": ["n2"],
            },
            {
                "id": "n2",
                "base_id": "axisymmetric_base",
                "op": "cut_center_bore",
                "phase": "primary_cut",
                "params": {"diameter_mm": 10, "axis": "Z"},
                "depends_on": ["n1"],
            },
        ])
        report = validate_graph_dag(spec)
        assert not report.ok
        assert any("Cycle" in i.message for i in report.issues)

    def test_valid_dag_passes(self):
        spec = _make_spec(nodes=[
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
            },
            {
                "id": "n2",
                "base_id": "axisymmetric_base",
                "op": "cut_center_bore",
                "phase": "primary_cut",
                "params": {"diameter_mm": 10, "axis": "Z"},
                "depends_on": ["n1"],
            },
        ])
        report = validate_graph_dag(spec)
        assert report.ok


class TestBaseSemantics:
    def test_missing_base_solid_fails(self):
        spec = _make_spec(nodes=[
            {
                "id": "n1",
                "base_id": "axisymmetric_base",
                "op": "cut_center_bore",
                "phase": "primary_cut",
                "params": {"diameter_mm": 10, "axis": "Z"},
            }
        ])
        report = validate_base_semantics(spec)
        assert not report.ok
        assert any("missing_base_solid" in i.code for i in report.issues)


class TestFullValidation:
    def test_valid_graph_passes_full(self):
        spec = _make_spec()
        report = run_graph_validation(spec)
        assert report.ok

    def test_unknown_base_in_full_validation_fails(self):
        spec = _make_spec(selected_bases=[
            {"base_id": "fake_base", "base_version": "0.1.0"}
        ], nodes=[
            {
                "id": "n1", "base_id": "fake_base",
                "op": "some_op", "phase": "base_solid",
                "params": {},
            }
        ])
        report = run_graph_validation(spec)
        assert not report.ok

    def test_extra_code_field_rejected(self):
        """Verify that extra field on GenerativeCADSpec is rejected by Pydantic."""
        with pytest.raises(ValueError):
            GenerativeCADSpec.model_validate({
                "part_name": "test",
                "selected_bases": [
                    {"base_id": "axisymmetric_base", "base_version": "0.1.0"}
                ],
                "feature_graph": {"nodes": [
                    {
                        "id": "n1",
                        "base_id": "axisymmetric_base",
                        "op": "revolve_profile",
                        "phase": "base_solid",
                        "params": {
                            "axis": "Z",
                            "profile_stations": [
                                {"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 10},
                            ],
                        },
                    }
                ]},
                "python_code": "import os; os.system('rm -rf /')",
            })
