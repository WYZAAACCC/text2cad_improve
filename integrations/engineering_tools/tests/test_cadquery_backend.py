"""Test CadQuery backend compiler without requiring CadQuery installation."""

import pytest
from seekflow_engineering_tools.cadquery_backend.compiler import (
    compile_cad_ir_to_cadquery_script,
    CadQueryCompileError,
)
from seekflow_engineering_tools.ir.cad import CADPartSpec


class TestCadQueryCompiler:
    def test_compiles_box_recipe(self):
        spec = CADPartSpec.model_validate({
            "name": "box_test",
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
        script = compile_cad_ir_to_cadquery_script(spec)
        assert "import cadquery as cq" in script
        assert "box" in script
        assert "100" in script
        assert "50" in script
        assert "30" in script

    def test_compiles_flanged_hub_recipe(self):
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
        })
        script = compile_cad_ir_to_cadquery_script(spec)
        assert "Workplane" in script
        assert "polarArray" in script
        assert "hole" in script

    def test_compiles_l_bracket_recipe(self):
        spec = CADPartSpec.model_validate({
            "name": "bracket",
            "units": "mm",
            "target_backend": ["cadquery"],
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
        script = compile_cad_ir_to_cadquery_script(spec)
        assert "Workplane" in script

    def test_compiles_block_with_hole_recipe(self):
        spec = CADPartSpec.model_validate({
            "name": "bwh",
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
        script = compile_cad_ir_to_cadquery_script(spec)
        assert "box" in script
        assert "hole" in script

    def test_compiles_stepped_block_recipe(self):
        spec = CADPartSpec.model_validate({
            "name": "stepped",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [{
                "id": "main",
                "type": "recipe",
                "recipe_name": "stepped_block",
                "parameters": {
                    "base_length_mm": 80,
                    "base_width_mm": 80,
                    "base_height_mm": 20,
                    "top_length_mm": 60,
                    "top_width_mm": 60,
                    "top_height_mm": 30,
                }
            }],
        })
        script = compile_cad_ir_to_cadquery_script(spec)
        assert "box" in script
        assert "extrude" in script

    def test_compiles_spur_gear_recipe(self):
        spec = CADPartSpec.model_validate({
            "name": "gear",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [{
                "id": "main",
                "type": "recipe",
                "recipe_name": "spur_gear",
                "parameters": {
                    "module_mm": 3,
                    "teeth": 20,
                    "face_width_mm": 20,
                    "bore_dia_mm": 15,
                }
            }],
        })
        script = compile_cad_ir_to_cadquery_script(spec)
        assert "polyline" in script
        assert "hole" in script

    def test_compiles_with_step_output(self):
        spec = CADPartSpec.model_validate({
            "name": "box",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [{
                "id": "main",
                "type": "recipe",
                "recipe_name": "box",
                "parameters": {"length_mm": 10, "width_mm": 10, "height_mm": 10},
            }],
        })
        script = compile_cad_ir_to_cadquery_script(spec, out_step="output.step")
        assert "exporters.export" in script
        assert "output.step" in script

    def test_compiles_extrude_feature(self):
        spec = CADPartSpec.model_validate({
            "name": "ext",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [{
                "id": "e1",
                "type": "extrude",
                "sketch": {
                    "plane": "XY",
                    "profile": {
                        "type": "rectangle",
                        "width_mm": 50,
                        "height_mm": 30,
                    },
                },
                "depth_mm": 20,
            }],
        })
        script = compile_cad_ir_to_cadquery_script(spec)
        assert "Workplane" in script
        assert "rect" in script
        assert "extrude" in script

    def test_unknown_recipe_raises(self):
        spec = CADPartSpec.model_validate({
            "name": "bad",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [{
                "id": "main",
                "type": "recipe",
                "recipe_name": "unknown_recipe_xyz",
                "parameters": {},
            }],
        })
        with pytest.raises(CadQueryCompileError):
            compile_cad_ir_to_cadquery_script(spec)

    def test_compiles_all_nine_recipes(self):
        """Verify all recipe generators produce non-empty code."""
        from seekflow_engineering_tools.cadquery_backend.recipes import (
            CADQUERY_RECIPE_GENERATORS,
        )
        from seekflow_engineering_tools.recipes.registry import get_recipe_definition

        assert len(CADQUERY_RECIPE_GENERATORS) >= 9

        for name, gen in CADQUERY_RECIPE_GENERATORS.items():
            rd = get_recipe_definition(name)
            assert rd is not None, f"No recipe definition for '{name}'"

            # Build a minimal valid params dict from recipe definition
            params = {}
            for p in rd.parameters:
                if p.required:
                    if p.type == "int":
                        params[p.name] = 1
                    else:
                        params[p.name] = 10.0

            result = gen(params)
            assert isinstance(result, str), f"Recipe '{name}' returned non-string"
            assert len(result) > 0, f"Recipe '{name}' returned empty string"
