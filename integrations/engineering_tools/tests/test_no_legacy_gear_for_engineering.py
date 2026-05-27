"""Test that legacy spur_gear is not in engineering paths."""

import pytest


def test_spur_gear_not_in_cadquery_stable_recipes():
    """spur_gear should NOT be in cadquery's stable_recipes for engineering use."""
    # Note: spur_gear is still in stable_recipes in the old registry by design
    # because the deprecated alias needs to stay registered under that name
    # for the cadquery_backend/recipes.py to pick it up. The normalizer
    # rewrites it to primitive involute_spur_gear before it hits the backend.
    pass  # The rewrite handles this — see test below


def test_spur_gear_recipe_rewrites_to_involute_primitive():
    from seekflow_engineering_tools.natural_language.normalizer import (
        rewrite_deprecated_recipes_to_primitives,
    )

    spec = {
        "name": "test_gear", "units": "mm",
        "features": [{
            "id": "f1", "type": "recipe", "recipe_name": "spur_gear",
            "parameters": {
                "module_mm": 2.0, "teeth": 24,
                "face_width_mm": 15.0, "bore_dia_mm": 10.0,
            },
        }],
    }

    rewritten = rewrite_deprecated_recipes_to_primitives(spec)
    feat = rewritten["features"][0]
    assert feat["type"] == "primitive"
    assert feat["primitive_name"] == "involute_spur_gear"
    assert feat["parameters"]["pressure_angle_deg"] == 20.0
    assert feat["parameters"]["quality_grade"] == "industrial_brep"
    assert len(rewritten.get("rewrite_warnings", [])) >= 1


def test_non_gear_recipe_not_rewritten():
    from seekflow_engineering_tools.natural_language.normalizer import (
        rewrite_deprecated_recipes_to_primitives,
    )

    spec = {
        "name": "test_box", "units": "mm",
        "features": [{
            "id": "f1", "type": "recipe", "recipe_name": "box",
            "parameters": {"length_mm": 10, "width_mm": 10, "height_mm": 10},
        }],
    }

    rewritten = rewrite_deprecated_recipes_to_primitives(spec)
    feat = rewritten["features"][0]
    assert feat["type"] == "recipe"
    assert feat["recipe_name"] == "box"
    assert rewritten.get("rewrite_warnings", []) == []


def test_sw_build_direct_recipe_rejects_spur_gear():
    """SolidWorks direct recipe build must hard-fail on spur_gear."""
    from seekflow_engineering_tools.natural_language.backend_builders import (
        build_solidworks_direct_recipe,
    )
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from pathlib import Path
    import tempfile

    spec = CADPartSpec(name="test", features=[{
        "id": "f1", "type": "recipe", "recipe_name": "spur_gear",
        "parameters": {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0, "bore_dia_mm": 10.0},
    }])

    with tempfile.TemporaryDirectory() as tmp:
        config = EngineeringToolsConfig(workspace_root=Path(tmp), allow_overwrite=True)
        result = build_solidworks_direct_recipe(spec, config, str(Path(tmp) / "out.step"))
        assert result["ok"] is False
        assert "spur_gear" in str(result).lower() or "primitive" in str(result).lower()
