"""Test axisymmetric_turbine_disk mechanical validation."""

import pytest

VALID_PARAMS = {
    "outer_dia_mm": 480.0,
    "bore_dia_mm": 80.0,
    "axial_width_mm": 60.0,
    "hub_outer_dia_mm": 200.0,
    "web_outer_dia_mm": 340.0,
    "rim_inner_dia_mm": 400.0,
    "hub_width_mm": 60.0,
    "web_width_mm": 32.0,
    "rim_width_mm": 56.0,
    "hub_fillet_radius_mm": 0.0,
    "web_fillet_radius_mm": 0.0,
    "rim_fillet_radius_mm": 0.0,
    "edge_chamfer_mm": 0.0,
    "bolt_hole_count": 12,
    "bolt_pcd_mm": 140.0,
    "bolt_hole_dia_mm": 10.0,
    "bolt_hole_axis": "Z",
    "lightening_hole_count": 8,
    "lightening_hole_pcd_mm": 280.0,
    "lightening_hole_dia_mm": 24.0,
    "lightening_hole_axis": "Z",
    "cooling_hole_count": 24,
    "cooling_hole_pcd_mm": 430.0,
    "cooling_hole_dia_mm": 5.0,
    "cooling_hole_axis": "Z",
    "quality_grade": "concept_geometry",
    "non_flight_reference_only": True,
    "rim_slot_count": 0,
    "rim_slot_style": "none",
    "front_hub_sleeve_height_mm": 0.0,
    "rear_hub_sleeve_height_mm": 0.0,
}

VALID_METADATA = {
    "primitive": "axisymmetric_turbine_disk",
    "kernel": "cadquery_turbine_disk_reference_v5",
    "parameters": dict(VALID_PARAMS),
    "reference_dimensions": {
        "outer_dia_mm": 480.0,
        "bore_dia_mm": 80.0,
        "axial_width_mm": 60.0,
        "hub_outer_dia_mm": 200.0,
        "web_outer_dia_mm": 340.0,
        "rim_inner_dia_mm": 400.0,
        "hub_width_mm": 60.0,
        "web_width_mm": 32.0,
        "rim_width_mm": 56.0,
        "bolt_hole_count": 12,
        "lightening_hole_count": 8,
        "cooling_hole_count": 24,
        "coverplate_bolt_count": 0,
        "balance_hole_count": 0,
        "rim_slot_count": 0,
        "rim_slot_style": "none",
        "rim_slot_orientation": "axial_through",
        "rim_slot_depth_mm": 0.0,
        "rim_slot_width_mm": 0.0,
        "rim_slot_opens_front_face": False,
        "rim_slot_opens_back_face": False,
        "rim_slot_opens_outer_diameter": False,
        "rim_slot_z_min_mm": 0.0,
        "rim_slot_z_max_mm": 0.0,
        "rim_slot_profile_max_x_mm": 0.0,
        "rim_slot_profile_min_x_mm": 0.0,
        "front_hub_sleeve_height_mm": 0.0,
        "front_hub_sleeve_outer_dia_mm": 0.0,
        "front_hub_sleeve_inner_dia_mm": 0.0,
        "expected_periodic_slot_count": 0,
        "expected_through_hole_count": 45,
        "expected_bbox_mm": [480.0, 480.0, 60.0],
    },
    "geometry_family": "axisymmetric_base_with_symmetric_multistage_fir_tree_slots",
    "axial_zones": {
        "rim_z_min_mm": -28.0, "rim_z_max_mm": 28.0,
        "hub_z_min_mm": -30.0, "hub_z_max_mm": 30.0,
        "web_z_min_mm": -16.0, "web_z_max_mm": 16.0,
        "base_z_min_mm": -30.0, "base_z_max_mm": 30.0,
    },
    "slot_generation": {
        "version": "rim_slot_v5_symmetric_multistage",
        "orientation": "axial_through",
        "profile_symmetry": "mirror_y",
        "is_mirror_symmetric": True,
        "stage_count": 0,
        "stage_stations": [],
        "socket_mode": "internal_lobes",
        "exposes_lobes_on_od": False,
        "opens_front_face": False,
        "opens_back_face": False,
        "opens_outer_diameter": False,
        "z_min_mm": 0.0,
        "z_max_mm": 0.0,
        "rim_z_min_mm": -28.0,
        "rim_z_max_mm": 28.0,
        "profile_max_x_mm": 0.0,
        "profile_min_x_mm": 0.0,
        "outer_radius_mm": 240.0,
        "through_clearance_mm": 2.0,
        "outer_clearance_mm": 4.0,
    },
    "visual_fidelity": {
        "target": "reference_turbine_rotor_disk",
        "contains_cyclic_rim_slots": False,
        "contains_axial_through_rim_slots": False,
        "contains_symmetric_fir_tree_slots": False,
        "contains_multistage_sidewall_grooves": False,
        "contains_hub_sleeve": False,
        "contains_annular_details": False,
        "contains_coverplate_interface": False,
        "contains_real_blade_attachment": False,
    },
    "rim_features": {
        "slot_count": 0,
        "slot_style": "none",
        "slot_orientation": "axial_through",
        "slot_depth_mm": 0.0,
        "slot_width_mm": 0.0,
        "slot_profile_points_xy": [],
        "reference_only": True,
    },
    "hub_sleeve": {
        "front_enabled": False,
        "rear_enabled": False,
        "front_outer_dia_mm": 0.0,
        "front_inner_dia_mm": 0.0,
        "front_height_mm": 0.0,
    },
    "annular_details": {
        "enabled": False,
        "mid_web_recess": False,
        "outer_rim_recess": False,
        "seal_lands": 0,
    },
    "safety": {
        "non_flight_reference_only": True,
        "not_for_manufacturing": True,
        "not_airworthy": True,
        "not_certified": True,
        "not_for_installation": True,
        "no_structural_validation": True,
        "no_life_prediction": True,
    },
}

VALID_INSPECTION = {
    "bbox_mm": [480.0, 480.0, 60.0],
    "solid_count": 1,
}


def test_happy_path_ok():
    from seekflow_engineering_tools.mechanical_validation.turbomachinery_validation import (
        validate_axisymmetric_turbine_disk_result,
    )
    result = validate_axisymmetric_turbine_disk_result(
        params=VALID_PARAMS,
        inspection=VALID_INSPECTION,
        metadata=VALID_METADATA,
        tolerance_mm=0.75,
    )
    assert result["ok"] is True
    assert result["primitive"] == "axisymmetric_turbine_disk"
    assert result["kernel"] == "cadquery_turbine_disk_reference_v5"


def test_metadata_missing_fails():
    from seekflow_engineering_tools.mechanical_validation.turbomachinery_validation import (
        validate_axisymmetric_turbine_disk_result,
    )
    result = validate_axisymmetric_turbine_disk_result(
        params=VALID_PARAMS,
        inspection=VALID_INSPECTION,
        metadata=None,
        tolerance_mm=0.75,
    )
    assert result["ok"] is False
    assert any("metadata_missing" in i["code"] for i in result["issues"])


def test_kernel_mismatch_fails():
    from seekflow_engineering_tools.mechanical_validation.turbomachinery_validation import (
        validate_axisymmetric_turbine_disk_result,
    )
    md = dict(VALID_METADATA, kernel="wrong_kernel")
    result = validate_axisymmetric_turbine_disk_result(
        params=VALID_PARAMS,
        inspection=VALID_INSPECTION,
        metadata=md,
        tolerance_mm=0.75,
    )
    assert result["ok"] is False
    assert any("kernel_mismatch" in i["code"] for i in result["issues"])


def test_primitive_mismatch_fails():
    from seekflow_engineering_tools.mechanical_validation.turbomachinery_validation import (
        validate_axisymmetric_turbine_disk_result,
    )
    md = dict(VALID_METADATA, primitive="wrong_primitive")
    result = validate_axisymmetric_turbine_disk_result(
        params=VALID_PARAMS,
        inspection=VALID_INSPECTION,
        metadata=md,
        tolerance_mm=0.75,
    )
    assert result["ok"] is False
    assert any("primitive_mismatch" in i["code"] for i in result["issues"])


def test_bbox_mismatch_fails():
    from seekflow_engineering_tools.mechanical_validation.turbomachinery_validation import (
        validate_axisymmetric_turbine_disk_result,
    )
    insp = {"bbox_mm": [100.0, 100.0, 10.0], "solid_count": 1}
    result = validate_axisymmetric_turbine_disk_result(
        params=VALID_PARAMS,
        inspection=insp,
        metadata=VALID_METADATA,
        tolerance_mm=0.5,
    )
    assert result["ok"] is False
    assert any("bbox" in i["code"] for i in result["issues"])


def test_body_count_mismatch_fails():
    from seekflow_engineering_tools.mechanical_validation.turbomachinery_validation import (
        validate_axisymmetric_turbine_disk_result,
    )
    insp = {"bbox_mm": [480.0, 480.0, 60.0], "solid_count": 3}
    result = validate_axisymmetric_turbine_disk_result(
        params=VALID_PARAMS,
        inspection=insp,
        metadata=VALID_METADATA,
        tolerance_mm=0.75,
    )
    assert result["ok"] is False
    assert any("body_count" in i["code"] for i in result["issues"])


def test_non_flight_false_fails():
    from seekflow_engineering_tools.mechanical_validation.turbomachinery_validation import (
        validate_axisymmetric_turbine_disk_result,
    )
    p = dict(VALID_PARAMS, non_flight_reference_only=False)
    result = validate_axisymmetric_turbine_disk_result(
        params=p,
        inspection=VALID_INSPECTION,
        metadata=VALID_METADATA,
        tolerance_mm=0.75,
    )
    assert result["ok"] is False
    assert any("non_flight" in i["code"] for i in result["issues"])


def test_quality_grade_invalid_fails():
    from seekflow_engineering_tools.mechanical_validation.turbomachinery_validation import (
        validate_axisymmetric_turbine_disk_result,
    )
    p = dict(VALID_PARAMS, quality_grade="flight_ready")
    result = validate_axisymmetric_turbine_disk_result(
        params=p,
        inspection=VALID_INSPECTION,
        metadata=VALID_METADATA,
        tolerance_mm=0.75,
    )
    assert result["ok"] is False
    assert any("quality_grade" in i["code"] for i in result["issues"])


def test_expected_kernel_mismatch_fails():
    from seekflow_engineering_tools.mechanical_validation.turbomachinery_validation import (
        validate_axisymmetric_turbine_disk_result,
    )
    result = validate_axisymmetric_turbine_disk_result(
        params=VALID_PARAMS,
        inspection=VALID_INSPECTION,
        metadata=VALID_METADATA,
        tolerance_mm=0.75,
        expected={"expected_kernel": "cq_gears"},
    )
    assert result["ok"] is False
    assert any("expected_kernel" in i["code"] for i in result["issues"])


def test_params_mismatch_fails():
    from seekflow_engineering_tools.mechanical_validation.turbomachinery_validation import (
        validate_axisymmetric_turbine_disk_result,
    )
    md = dict(VALID_METADATA, parameters=dict(VALID_PARAMS, rim_slot_count=999))
    result = validate_axisymmetric_turbine_disk_result(
        params=VALID_PARAMS,
        inspection=VALID_INSPECTION,
        metadata=md,
        tolerance_mm=0.5,
    )
    assert result["ok"] is False
    assert any("parameter_mismatch" in i["code"] for i in result["issues"])
