"""Test involute spur gear reference dimension calculations."""

import math

import pytest


def test_24teeth_m2_dimensions():
    from seekflow_engineering_tools.geometry_primitives.gears.standards import (
        spur_gear_reference_dimensions,
    )

    params = {
        "module_mm": 2.0,
        "teeth": 24,
        "pressure_angle_deg": 20.0,
        "face_width_mm": 15.0,
        "addendum_coefficient": 1.0,
        "clearance_coefficient": 0.25,
        "profile_shift_coefficient": 0.0,
    }
    dims = spur_gear_reference_dimensions(params)

    # pitch_d = m * z = 2 * 24 = 48
    assert dims["pitch_diameter_mm"] == pytest.approx(48.0, rel=1e-9)
    # outer_d = m * (z + 2*ha) = 2 * (24 + 2) = 52
    assert dims["outer_diameter_mm"] == pytest.approx(52.0, rel=1e-9)
    # base_d = pitch_d * cos(alpha) = 48 * cos(20°) ≈ 45.105
    assert dims["base_diameter_mm"] == pytest.approx(48.0 * math.cos(math.radians(20)), rel=1e-9)
    # root_d = pitch_d - 2*m*(ha + c) = 48 - 4*(1.25) = 43
    assert dims["root_diameter_mm"] == pytest.approx(43.0, rel=1e-9)
    # root < pitch < outer
    assert dims["root_diameter_mm"] < dims["pitch_diameter_mm"] < dims["outer_diameter_mm"]
    # base < outer (for PA=20°)
    assert dims["base_diameter_mm"] < dims["outer_diameter_mm"]
    # circular_pitch = pi * m
    assert dims["circular_pitch_mm"] == pytest.approx(math.pi * 2.0, rel=1e-9)


def test_profile_shift_affects_diameters():
    from seekflow_engineering_tools.geometry_primitives.gears.standards import (
        spur_gear_reference_dimensions,
    )

    params_no_shift = {
        "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
        "profile_shift_coefficient": 0.0,
    }
    params_with_shift = {
        "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
        "profile_shift_coefficient": 0.5,
    }

    dims0 = spur_gear_reference_dimensions(params_no_shift)
    dims1 = spur_gear_reference_dimensions(params_with_shift)

    # Positive profile shift increases outer and root diameters
    assert dims1["outer_diameter_mm"] > dims0["outer_diameter_mm"]
    assert dims1["root_diameter_mm"] > dims0["root_diameter_mm"]


def test_backlash_reduces_tooth_thickness():
    from seekflow_engineering_tools.geometry_primitives.gears.standards import (
        spur_gear_reference_dimensions,
    )

    params_no_backlash = {
        "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0, "backlash_mm": 0.0,
    }
    params_with_backlash = {
        "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0, "backlash_mm": 0.05,
    }

    dims0 = spur_gear_reference_dimensions(params_no_backlash)
    dims1 = spur_gear_reference_dimensions(params_with_backlash)

    assert dims1["tooth_thickness_pitch_mm"] < dims0["tooth_thickness_pitch_mm"]


def test_different_pressure_angles():
    from seekflow_engineering_tools.geometry_primitives.gears.standards import (
        spur_gear_reference_dimensions,
    )

    dims_145 = spur_gear_reference_dimensions({
        "module_mm": 3.0, "teeth": 20, "face_width_mm": 20.0,
        "pressure_angle_deg": 14.5,
    })
    dims_20 = spur_gear_reference_dimensions({
        "module_mm": 3.0, "teeth": 20, "face_width_mm": 20.0,
        "pressure_angle_deg": 20.0,
    })
    dims_25 = spur_gear_reference_dimensions({
        "module_mm": 3.0, "teeth": 20, "face_width_mm": 20.0,
        "pressure_angle_deg": 25.0,
    })

    # Larger PA → smaller base diameter (cos decreases for PA > 0 up to 90)
    assert dims_145["base_diameter_mm"] > dims_20["base_diameter_mm"] > dims_25["base_diameter_mm"]
    # Pitch diameter is independent of PA
    assert dims_145["pitch_diameter_mm"] == dims_20["pitch_diameter_mm"]
