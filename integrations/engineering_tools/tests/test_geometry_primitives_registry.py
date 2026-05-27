"""Test geometry primitives registry."""

import pytest


def test_primitive_registry_loaded():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        PRIMITIVE_REGISTRY,
        list_primitive_names,
    )
    assert "involute_spur_gear" in PRIMITIVE_REGISTRY
    names = list_primitive_names()
    assert "involute_spur_gear" in names


def test_get_primitive():
    from seekflow_engineering_tools.geometry_primitives.registry import get_primitive

    pd = get_primitive("involute_spur_gear")
    assert pd is not None
    assert pd.name == "involute_spur_gear"
    assert pd.category == "gear"
    assert "cadquery" in pd.supported_backends


def test_backend_supports_primitive():
    from seekflow_engineering_tools.geometry_primitives.registry import backend_supports_primitive

    assert backend_supports_primitive("cadquery", "involute_spur_gear") is True
    assert backend_supports_primitive("solidworks2025", "involute_spur_gear") is True
    assert backend_supports_primitive("nx12", "involute_spur_gear") is True
    assert backend_supports_primitive("unknown_backend", "involute_spur_gear") is False
    assert backend_supports_primitive("cadquery", "nonexistent") is False


def test_normalize_primitive_parameters_defaults():
    from seekflow_engineering_tools.geometry_primitives.registry import normalize_primitive_parameters

    params = {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}
    normalized = normalize_primitive_parameters("involute_spur_gear", params)

    assert normalized["pressure_angle_deg"] == 20.0
    assert normalized["addendum_coefficient"] == 1.0
    assert normalized["clearance_coefficient"] == 0.25
    assert normalized["profile_shift_coefficient"] == 0.0
    assert normalized["backlash_mm"] == 0.0
    assert normalized["root_fillet_radius_mm"] == 0.0
    assert normalized["quality_grade"] == "industrial_brep"
    assert normalized["bore_dia_mm"] == 0.0


def test_normalize_primitive_parameters_rejects_unknown():
    from seekflow_engineering_tools.geometry_primitives.registry import normalize_primitive_parameters

    with pytest.raises(ValueError, match="Unknown parameter"):
        normalize_primitive_parameters("involute_spur_gear", {
            "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
            "invalid_param": 42,
        })
