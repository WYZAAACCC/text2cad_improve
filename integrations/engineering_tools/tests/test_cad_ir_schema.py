"""Test CAD-IR Pydantic schema validation."""

import pytest
from seekflow_engineering_tools.ir.cad import CADPartSpec, RecipeFeature, ValidationSpec


class TestCADPartSpec:
    def test_minimal_valid_spec(self):
        spec = CADPartSpec.model_validate({
            "name": "test_part",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [{
                "id": "main",
                "type": "recipe",
                "recipe_name": "box",
                "parameters": {
                    "length_mm": 100,
                    "width_mm": 50,
                    "height_mm": 30,
                }
            }],
        })
        assert spec.name == "test_part"
        assert spec.units == "mm"
        assert len(spec.features) == 1

    def test_units_must_be_mm(self):
        with pytest.raises(ValueError, match="mm"):
            CADPartSpec.model_validate({
                "name": "bad",
                "units": "m",
                "target_backend": ["cadquery"],
                "features": [{
                    "id": "f1",
                    "type": "recipe",
                    "recipe_name": "box",
                    "parameters": {"length_mm": 10, "width_mm": 10, "height_mm": 10},
                }],
            })

    def test_duplicate_feature_ids_rejected(self):
        with pytest.raises(ValueError, match="unique"):
            CADPartSpec.model_validate({
                "name": "dup",
                "units": "mm",
                "target_backend": ["cadquery"],
                "features": [
                    {
                        "id": "same_id",
                        "type": "recipe",
                        "recipe_name": "box",
                        "parameters": {"length_mm": 10, "width_mm": 10, "height_mm": 10},
                    },
                    {
                        "id": "same_id",
                        "type": "recipe",
                        "recipe_name": "box",
                        "parameters": {"length_mm": 20, "width_mm": 20, "height_mm": 20},
                    },
                ],
            })

    def test_flanged_hub_recipe_validates(self):
        spec = CADPartSpec.model_validate({
            "name": "hub",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [{
                "id": "main",
                "type": "recipe",
                "recipe_name": "flanged_hub",
                "parameters": {
                    "flange_dia_mm": 80,
                    "flange_thickness_mm": 12,
                    "hub_dia_mm": 40,
                    "hub_height_mm": 28,
                    "bore_dia_mm": 20,
                    "bolt_pcd_mm": 60,
                    "bolt_dia_mm": 8,
                    "bolt_count": 4,
                }
            }],
            "validation": {
                "expected_bbox_mm": [80, 80, 40],
                "expected_body_count": 1,
                "expected_through_hole_count": 5,
                "tolerance_mm": 0.2,
            },
        })
        assert spec.name == "hub"
        assert spec.validation.expected_bbox_mm == [80, 80, 40]
        assert spec.validation.expected_through_hole_count == 5

    def test_l_bracket_recipe_validates(self):
        spec = CADPartSpec.model_validate({
            "name": "bracket",
            "units": "mm",
            "target_backend": ["nx12", "cadquery"],
            "features": [{
                "id": "main",
                "type": "recipe",
                "recipe_name": "l_bracket",
                "parameters": {
                    "base_length_mm": 100,
                    "base_width_mm": 60,
                    "thickness_mm": 15,
                    "leg_height_mm": 60,
                }
            }],
        })
        assert len(spec.target_backend) == 2

    def test_block_with_hole_recipe_validates(self):
        spec = CADPartSpec.model_validate({
            "name": "block_hole",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [{
                "id": "main",
                "type": "recipe",
                "recipe_name": "block_with_hole",
                "parameters": {
                    "length_mm": 100,
                    "width_mm": 60,
                    "height_mm": 40,
                    "hole_dia_mm": 16,
                }
            }],
        })
        assert spec.name == "block_hole"

    def test_extrude_feature_parses(self):
        spec = CADPartSpec.model_validate({
            "name": "ext_part",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [{
                "id": "ext1",
                "type": "extrude",
                "sketch": {
                    "plane": "XY",
                    "origin_mm": [0, 0, 0],
                    "profile": {
                        "type": "rectangle",
                        "width_mm": 50,
                        "height_mm": 30,
                        "centered": True,
                    },
                },
                "depth_mm": 20,
            }],
        })
        assert len(spec.features) == 1
        assert spec.features[0].type == "extrude"

    def test_hole_feature_parses(self):
        spec = CADPartSpec.model_validate({
            "name": "hole_part",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [{
                "id": "h1",
                "type": "hole",
                "diameter_mm": 10,
                "position_mm": [25, 25, 0],
                "axis": "Z",
                "through_all": True,
            }],
        })
        assert spec.features[0].type == "hole"
        assert spec.features[0].diameter_mm == 10

    def test_validation_defaults(self):
        spec = CADPartSpec.model_validate({
            "name": "test",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [],
        })
        assert spec.validation.tolerance_mm == 0.1
        assert spec.outputs.native is True
        assert spec.outputs.step is True

    def test_default_target_backend(self):
        spec = CADPartSpec.model_validate({
            "name": "test",
            "units": "mm",
            "features": [],
        })
        assert spec.target_backend == ["cadquery"]
