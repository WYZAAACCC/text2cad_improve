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
}

VALID_METADATA = {
    "primitive": "axisymmetric_turbine_disk",
    "kernel": "cadquery_axisymmetric_revolve_v0",
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
        "expected_through_hole_count": 45,
    },
    "safety": {
        "non_flight_reference_only": True,
        "not_for_manufacturing": True,
        "not_airworthy": True,
        "not_certified": True,
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
    assert result["kernel"] == "cadquery_axisymmetric_revolve_v0"


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
    md = dict(VALID_METADATA, parameters=dict(VALID_PARAMS, outer_dia_mm=999.0))
    result = validate_axisymmetric_turbine_disk_result(
        params=VALID_PARAMS,
        inspection=VALID_INSPECTION,
        metadata=md,
        tolerance_mm=0.5,
    )
    assert result["ok"] is False
    assert any("parameter_mismatch" in i["code"] for i in result["issues"])
