"""Test geometry preflight for axisymmetric and sketch_extrude bases."""

import pytest

from seekflow_engineering_tools.generative_cad.ir import GenerativeCADSpec
from seekflow_engineering_tools.generative_cad.preflight import run_geometry_preflight


def _make_spec(nodes, **overrides):
    data = {
        "part_name": "test",
        "selected_bases": [
            {"base_id": "axisymmetric_base", "base_version": "0.1.0"}
        ],
        "feature_graph": {"nodes": nodes},
        **overrides,
    }
    return GenerativeCADSpec.model_validate(data)


class TestAxisymmetricPreflight:
    def test_hole_outside_outer_radius(self):
        spec = _make_spec([
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
                "op": "cut_circular_hole_pattern",
                "phase": "pattern_cut",
                "params": {
                    "count": 6,
                    "pcd_mm": 120,
                    "hole_dia_mm": 10,
                    "axis": "Z",
                    "through_all": True,
                },
            },
        ])
        report = run_geometry_preflight(spec)
        assert not report["ok"]
        assert any(
            "outside_material" in i.get("code", "")
            for i in report["issues"]
        )

    def test_hole_intersects_bore(self):
        spec = _make_spec([
            {
                "id": "n1",
                "base_id": "axisymmetric_base",
                "op": "revolve_profile",
                "phase": "base_solid",
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 100, "z_front_mm": 0, "z_rear_mm": 10},
                        {"r_mm": 100, "z_front_mm": 10, "z_rear_mm": 20},
                    ],
                },
            },
            {
                "id": "n2",
                "base_id": "axisymmetric_base",
                "op": "cut_center_bore",
                "phase": "primary_cut",
                "params": {"diameter_mm": 80, "axis": "Z"},
            },
            {
                "id": "n3",
                "base_id": "axisymmetric_base",
                "op": "cut_circular_hole_pattern",
                "phase": "pattern_cut",
                "params": {
                    "count": 6,
                    "pcd_mm": 82,
                    "hole_dia_mm": 10,
                    "axis": "Z",
                    "through_all": True,
                },
            },
        ])
        report = run_geometry_preflight(spec)
        assert not report["ok"]
        assert any(
            "intersects_bore" in i.get("code", "")
            for i in report["issues"]
        )

    def test_pcd_hole_ligament_too_small(self):
        # Use large holes on a small PCD to create barely-touching holes
        spec = _make_spec([
            {
                "id": "n1",
                "base_id": "axisymmetric_base",
                "op": "revolve_profile",
                "phase": "base_solid",
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 200, "z_front_mm": 0, "z_rear_mm": 10},
                        {"r_mm": 200, "z_front_mm": 10, "z_rear_mm": 20},
                    ],
                },
            },
            {
                "id": "n2",
                "base_id": "axisymmetric_base",
                "op": "cut_circular_hole_pattern",
                "phase": "pattern_cut",
                "params": {
                    "count": 3,
                    "pcd_mm": 50,
                    "hole_dia_mm": 52,
                    "axis": "Z",
                    "through_all": True,
                },
            },
        ])
        report = run_geometry_preflight(spec)
        assert not report["ok"]
        assert any(
            "ligament_too_small" in i.get("code", "")
            for i in report["issues"]
        )

    def test_rim_slot_too_deep(self):
        spec = _make_spec([
            {
                "id": "n1",
                "base_id": "axisymmetric_base",
                "op": "revolve_profile",
                "phase": "base_solid",
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 100, "z_front_mm": 0, "z_rear_mm": 10},
                        {"r_mm": 100, "z_front_mm": 10, "z_rear_mm": 20},
                    ],
                },
            },
            {
                "id": "n2",
                "base_id": "axisymmetric_base",
                "op": "cut_center_bore",
                "phase": "primary_cut",
                "params": {"diameter_mm": 40, "axis": "Z"},
            },
            {
                "id": "n3",
                "base_id": "axisymmetric_base",
                "op": "cut_rim_slot_pattern",
                "phase": "rim_detail",
                "params": {
                    "count": 12,
                    "slot_depth_mm": 200,
                    "slot_profile": {
                        "kind": "symmetric_station_profile",
                        "stations": [
                            {"depth_mm": 0, "half_width_mm": 5},
                            {"depth_mm": 10, "half_width_mm": 8},
                        ],
                    },
                },
            },
        ])
        report = run_geometry_preflight(spec)
        assert not report["ok"]
        assert any(
            "rim_slot_too_deep" in i.get("code", "")
            for i in report["issues"]
        )

    def test_slot_depths_non_monotonic(self):
        """Slot depth non-monotonic should be caught by op params schema validation."""
        from seekflow_engineering_tools.generative_cad.graph_validation import validate_op_params_schema

        spec = _make_spec([
            {
                "id": "n1",
                "base_id": "axisymmetric_base",
                "op": "revolve_profile",
                "phase": "base_solid",
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 100, "z_front_mm": 0, "z_rear_mm": 10},
                        {"r_mm": 100, "z_front_mm": 10, "z_rear_mm": 20},
                    ],
                },
            },
            {
                "id": "n2",
                "base_id": "axisymmetric_base",
                "op": "cut_rim_slot_pattern",
                "phase": "rim_detail",
                "params": {
                    "count": 12,
                    "slot_depth_mm": 20,
                    "slot_profile": {
                        "kind": "symmetric_station_profile",
                        "stations": [
                            {"depth_mm": 10, "half_width_mm": 5},
                            {"depth_mm": 5, "half_width_mm": 8},
                        ],
                    },
                },
            },
        ])
        report = validate_op_params_schema(spec)
        assert not report.ok
        assert any("nondecreasing" in i.message.lower() for i in report.issues)

    def test_profile_station_z_inverted(self):
        spec = _make_spec([
            {
                "id": "n1",
                "base_id": "axisymmetric_base",
                "op": "revolve_profile",
                "phase": "base_solid",
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 50, "z_front_mm": 20, "z_rear_mm": 10},
                        {"r_mm": 30, "z_front_mm": 10, "z_rear_mm": 20},
                    ],
                },
            }
        ])
        report = run_geometry_preflight(spec)
        assert not report["ok"]
        assert any(
            "z_inverted" in i.get("code", "")
            for i in report["issues"]
        )

    def test_valid_graph_passes_preflight(self):
        spec = _make_spec([
            {
                "id": "n1",
                "base_id": "axisymmetric_base",
                "op": "revolve_profile",
                "phase": "base_solid",
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 100, "z_front_mm": 0, "z_rear_mm": 10},
                        {"r_mm": 80, "z_front_mm": 10, "z_rear_mm": 30},
                    ],
                },
            },
            {
                "id": "n2",
                "base_id": "axisymmetric_base",
                "op": "cut_center_bore",
                "phase": "primary_cut",
                "params": {"diameter_mm": 20, "axis": "Z"},
            },
        ])
        report = run_geometry_preflight(spec)
        assert report["ok"], f"Preflight should pass, got: {report['issues']}"


class TestSketchExtrudePreflight:
    def test_hole_spacing_too_small(self):
        from seekflow_engineering_tools.generative_cad.ir import GenerativeCADSpec
        spec = GenerativeCADSpec.model_validate({
            "part_name": "test_plate",
            "selected_bases": [
                {"base_id": "sketch_extrude_base", "base_version": "0.1.0"}
            ],
            "feature_graph": {
                "nodes": [
                    {
                        "id": "n1",
                        "base_id": "sketch_extrude_base",
                        "op": "extrude_rectangle",
                        "phase": "base_solid",
                        "params": {
                            "width_mm": 100,
                            "height_mm": 50,
                            "depth_mm": 10,
                        },
                    },
                    {
                        "id": "n2",
                        "base_id": "sketch_extrude_base",
                        "op": "cut_hole_pattern_linear",
                        "phase": "hole_pattern",
                        "params": {
                            "hole_dia_mm": 10,
                            "count_x": 2,
                            "count_y": 2,
                            "spacing_x_mm": 8,
                            "spacing_y_mm": 8,
                        },
                    },
                ]
            },
        })
        report = run_geometry_preflight(spec)
        assert not report["ok"]
        assert any(
            "spacing_too_small" in i.get("code", "")
            for i in report["issues"]
        )
