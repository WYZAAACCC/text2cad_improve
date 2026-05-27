"""Test mechanical validation for involute spur gear — fail-closed."""

import pytest


def test_validation_with_cq_gears_metadata():
    from seekflow_engineering_tools.mechanical_validation.gear_validation import (
        validate_involute_spur_gear_result,
    )

    params = {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}
    inspection = {"bbox_mm": [52.0, 52.0, 15.0]}
    metadata = {
        "kernel": "cq_gears",
        "primitive": "involute_spur_gear",
        "is_standard_involute": True,
        "reference_dimensions": {
            "pitch_diameter_mm": 48.0,
            "base_diameter_mm": 45.105,
            "outer_diameter_mm": 52.0,
            "root_diameter_mm": 43.0,
        },
    }

    result = validate_involute_spur_gear_result(params, inspection, metadata, tolerance_mm=0.5)
    assert result["ok"] is True
    assert result["kernel"] == "cq_gears"
    assert result["reference_dimensions"]["pitch_diameter_mm"] == 48.0


def test_validation_fails_on_fallback_unless_explicit():
    from seekflow_engineering_tools.mechanical_validation.gear_validation import (
        validate_involute_spur_gear_result,
    )

    params = {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}
    inspection = {"bbox_mm": [52.0, 52.0, 15.0]}
    metadata = {
        "kernel": "cadquery_visual_fallback",
        "primitive": "involute_spur_gear",
        "is_standard_involute": False,
        "reference_dimensions": {
            "pitch_diameter_mm": 48.0,
            "base_diameter_mm": 45.105,
            "outer_diameter_mm": 52.0,
            "root_diameter_mm": 43.0,
        },
    }

    # Without explicit allow → hard error
    result = validate_involute_spur_gear_result(params, inspection, metadata)
    issues = result["issues"]
    assert any("fallback" in i["code"].lower() for i in issues)
    assert result["kernel"] == "cadquery_visual_fallback"
    assert result["ok"] is False  # fail-closed: fallback not allowed by default


def test_validation_fallback_allowed_explicitly():
    from seekflow_engineering_tools.mechanical_validation.gear_validation import (
        validate_involute_spur_gear_result,
    )

    params = {
        "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
        "quality_grade": "visual_fallback",
    }
    inspection = {"bbox_mm": [52.0, 52.0, 15.0]}
    metadata = {
        "kernel": "cadquery_visual_fallback",
        "primitive": "involute_spur_gear",
        "is_standard_involute": False,
        "reference_dimensions": {
            "pitch_diameter_mm": 48.0,
            "base_diameter_mm": 45.105,
            "outer_diameter_mm": 52.0,
            "root_diameter_mm": 43.0,
        },
    }

    result = validate_involute_spur_gear_result(params, inspection, metadata)
    # Explicit quality_grade=visual_fallback — warning but not hard error
    assert result["kernel"] == "cadquery_visual_fallback"
    # bbox should still be ok


def test_validation_bbox_mismatch():
    from seekflow_engineering_tools.mechanical_validation.gear_validation import (
        validate_involute_spur_gear_result,
    )

    params = {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}
    inspection = {"bbox_mm": [30.0, 30.0, 5.0]}  # completely wrong
    metadata = {
        "kernel": "cq_gears",
        "primitive": "involute_spur_gear",
        "is_standard_involute": True,
        "reference_dimensions": {
            "pitch_diameter_mm": 48.0,
            "base_diameter_mm": 45.105,
            "outer_diameter_mm": 52.0,
            "root_diameter_mm": 43.0,
        },
    }

    result = validate_involute_spur_gear_result(params, inspection, metadata, tolerance_mm=0.5)
    assert result["ok"] is False  # bbox mismatch should be an error


def test_validation_missing_metadata():
    from seekflow_engineering_tools.mechanical_validation.gear_validation import (
        validate_involute_spur_gear_result,
    )

    params = {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}
    inspection = {"bbox_mm": [52.0, 52.0, 15.0]}

    result = validate_involute_spur_gear_result(params, inspection, None)
    assert result["kernel"] == "unknown"
    assert result["ok"] is False  # metadata missing is now a hard error
    assert any("metadata" in i["code"].lower() or "kernel_unknown" in i["code"].lower() for i in result["issues"])


def test_validation_reference_dimension_mismatch():
    from seekflow_engineering_tools.mechanical_validation.gear_validation import (
        validate_involute_spur_gear_result,
    )

    params = {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}
    inspection = {"bbox_mm": [52.0, 52.0, 15.0]}
    metadata = {
        "kernel": "cq_gears",
        "primitive": "involute_spur_gear",
        "is_standard_involute": True,
        "reference_dimensions": {
            "pitch_diameter_mm": 99.0,  # clearly wrong
            "base_diameter_mm": 99.0,   # clearly wrong
            "outer_diameter_mm": 99.0,  # clearly wrong
            "root_diameter_mm": 99.0,   # clearly wrong
        },
    }

    result = validate_involute_spur_gear_result(params, inspection, metadata, tolerance_mm=0.5)
    assert result["ok"] is False
    assert any("mismatch" in i["code"].lower() for i in result["issues"])


def test_validation_is_standard_involute_must_be_true():
    from seekflow_engineering_tools.mechanical_validation.gear_validation import (
        validate_involute_spur_gear_result,
    )

    params = {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}
    inspection = {"bbox_mm": [52.0, 52.0, 15.0]}
    metadata = {
        "kernel": "cq_gears",
        "primitive": "involute_spur_gear",
        "is_standard_involute": False,  # not standard!
        "reference_dimensions": {
            "pitch_diameter_mm": 48.0,
            "base_diameter_mm": 45.105,
            "outer_diameter_mm": 52.0,
            "root_diameter_mm": 43.0,
        },
    }

    result = validate_involute_spur_gear_result(params, inspection, metadata)
    assert result["ok"] is False
    assert any("not_standard" in i["code"].lower() for i in result["issues"])
