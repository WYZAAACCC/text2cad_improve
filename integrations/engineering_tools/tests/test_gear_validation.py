"""Test mechanical validation for involute spur gear."""

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


def test_validation_warns_on_fallback():
    from seekflow_engineering_tools.mechanical_validation.gear_validation import (
        validate_involute_spur_gear_result,
    )

    params = {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}
    inspection = {"bbox_mm": [52.0, 52.0, 15.0]}
    metadata = {
        "kernel": "cadquery_visual_fallback",
        "primitive": "involute_spur_gear",
        "reference_dimensions": {
            "pitch_diameter_mm": 48.0,
            "base_diameter_mm": 45.105,
            "outer_diameter_mm": 52.0,
            "root_diameter_mm": 43.0,
        },
    }

    result = validate_involute_spur_gear_result(params, inspection, metadata)
    # Should have warnings about fallback but shouldn't necessarily be a hard error
    issues = result["issues"]
    assert any("fallback" in i["code"].lower() for i in issues)
    assert result["kernel"] == "cadquery_visual_fallback"


def test_validation_bbox_mismatch():
    from seekflow_engineering_tools.mechanical_validation.gear_validation import (
        validate_involute_spur_gear_result,
    )

    params = {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}
    inspection = {"bbox_mm": [30.0, 30.0, 5.0]}  # completely wrong
    metadata = {
        "kernel": "cq_gears",
        "primitive": "involute_spur_gear",
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
    assert any("metadata" in i["code"].lower() or "kernel_unknown" in i["code"].lower() for i in result["issues"])
