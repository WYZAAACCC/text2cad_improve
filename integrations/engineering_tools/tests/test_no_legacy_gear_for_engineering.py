"""Test that legacy spur_gear recipe is rewritten to primitive for engineering use."""

import pytest


def test_spur_gear_recipe_rewritten_to_primitive():
    from seekflow_engineering_tools.natural_language.normalizer import (
        rewrite_deprecated_recipes_to_primitives,
    )

    spec = {
        "name": "test_gear", "units": "mm",
        "features": [{
            "id": "f1",
            "type": "recipe",
            "recipe_name": "spur_gear",
            "parameters": {
                "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
                "bore_dia_mm": 10.0,
            },
        }],
    }

    rewritten = rewrite_deprecated_recipes_to_primitives(spec)

    feat = rewritten["features"][0]
    assert feat["type"] == "primitive"
    assert feat["primitive_name"] == "involute_spur_gear"

    # Default params should be set
    assert feat["parameters"]["pressure_angle_deg"] == 20.0
    assert feat["parameters"]["addendum_coefficient"] == 1.0
    assert feat["parameters"]["quality_grade"] == "industrial_brep"

    # Original params preserved
    assert feat["parameters"]["module_mm"] == 2.0
    assert feat["parameters"]["teeth"] == 24

    # Warning should be emitted
    assert len(rewritten["rewrite_warnings"]) >= 1
    assert "spur_gear" in rewritten["rewrite_warnings"][0]


def test_non_gear_recipe_not_rewritten():
    from seekflow_engineering_tools.natural_language.normalizer import (
        rewrite_deprecated_recipes_to_primitives,
    )

    spec = {
        "name": "test_box", "units": "mm",
        "features": [{
            "id": "f1",
            "type": "recipe",
            "recipe_name": "box",
            "parameters": {"length_mm": 10, "width_mm": 10, "height_mm": 10},
        }],
    }

    rewritten = rewrite_deprecated_recipes_to_primitives(spec)
    feat = rewritten["features"][0]
    assert feat["type"] == "recipe"
    assert feat["recipe_name"] == "box"
    assert rewritten["rewrite_warnings"] == []
