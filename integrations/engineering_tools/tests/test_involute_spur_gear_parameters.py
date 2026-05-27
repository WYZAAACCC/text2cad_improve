"""Test involute spur gear parameter validation."""

import pytest


def test_valid_minimal_params():
    from seekflow_engineering_tools.geometry_primitives.gears.validator import (
        validate_involute_spur_gear_parameters,
    )
    errors = validate_involute_spur_gear_parameters({
        "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
    })
    assert errors == []


def test_defaults_applied_by_registry():
    from seekflow_engineering_tools.geometry_primitives.registry import normalize_primitive_parameters

    normalized = normalize_primitive_parameters("involute_spur_gear", {
        "module_mm": 3.0, "teeth": 30, "face_width_mm": 25.0,
    })
    assert normalized["pressure_angle_deg"] == 20.0
    assert normalized["addendum_coefficient"] == 1.0
    assert normalized["clearance_coefficient"] == 0.25
    assert normalized["profile_shift_coefficient"] == 0.0


def test_large_bore_rejected():
    from seekflow_engineering_tools.geometry_primitives.gears.validator import (
        validate_involute_spur_gear_parameters,
    )
    # Module 2, 24 teeth => root_diameter ~ 43mm, 0.85*root ~ 36.5mm
    errors = validate_involute_spur_gear_parameters({
        "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
        "bore_dia_mm": 40.0,  # too close to root
    })
    assert any("bore" in e.lower() for e in errors)


def test_module_must_be_positive():
    from seekflow_engineering_tools.geometry_primitives.gears.validator import (
        validate_involute_spur_gear_parameters,
    )
    errors = validate_involute_spur_gear_parameters({
        "module_mm": 0, "teeth": 24, "face_width_mm": 15.0,
    })
    assert any("module" in e.lower() for e in errors)


def test_teeth_at_least_6():
    from seekflow_engineering_tools.geometry_primitives.gears.validator import (
        validate_involute_spur_gear_parameters,
    )
    errors = validate_involute_spur_gear_parameters({
        "module_mm": 2.0, "teeth": 5, "face_width_mm": 15.0,
    })
    assert any("teeth" in e.lower() for e in errors)


def test_face_width_must_be_positive():
    from seekflow_engineering_tools.geometry_primitives.gears.validator import (
        validate_involute_spur_gear_parameters,
    )
    errors = validate_involute_spur_gear_parameters({
        "module_mm": 2.0, "teeth": 24, "face_width_mm": 0,
    })
    assert any("face_width" in e.lower() for e in errors)


def test_excessive_backlash_rejected():
    from seekflow_engineering_tools.geometry_primitives.gears.validator import (
        validate_involute_spur_gear_parameters,
    )
    # Module 2 => circular_pitch ≈ 6.28, 0.25*cp ≈ 1.57
    errors = validate_involute_spur_gear_parameters({
        "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
        "backlash_mm": 2.0,
    })
    assert any("backlash" in e.lower() for e in errors)


def test_diameter_ordering_violated():
    from seekflow_engineering_tools.geometry_primitives.gears.validator import (
        validate_involute_spur_gear_parameters,
    )
    # Extreme negative profile shift with small addendum causes outer_d < pitch_d
    errors = validate_involute_spur_gear_parameters({
        "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
        "profile_shift_coefficient": -1.0, "addendum_coefficient": 0.5,
    })
    assert any("diameter" in e.lower() or "Diameter" in e for e in errors)
