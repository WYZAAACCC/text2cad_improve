"""Test capability registry for backend routing and recipe support."""

from __future__ import annotations

from seekflow_engineering_tools.capabilities.registry import (
    CAPABILITIES,
    backend_supports_recipe,
    choose_backend,
    load_capability_registry,
    list_backend_recipes,
)
from seekflow_engineering_tools.ir.cad import CADPartSpec, RecipeFeature


def _make_spec(recipe_name: str, backend: str = "cadquery") -> CADPartSpec:
    # Provide minimal valid params for known recipes
    dummy_params = {
        "box": {"length_mm": 10, "width_mm": 10, "height_mm": 10},
        "cylinder": {"diameter_mm": 10, "height_mm": 10},
        "block_with_hole": {"length_mm": 10, "width_mm": 10, "height_mm": 10, "hole_dia_mm": 5},
        "l_bracket": {"base_length_mm": 10, "base_width_mm": 10, "thickness_mm": 5, "leg_height_mm": 10},
        "stepped_block": {"base_length_mm": 20, "base_width_mm": 20, "base_height_mm": 10, "top_length_mm": 10, "top_width_mm": 10, "top_height_mm": 10},
        "flanged_hub": {"flange_dia_mm": 80, "flange_thickness_mm": 10, "hub_dia_mm": 40, "hub_height_mm": 30, "bore_dia_mm": 20, "bolt_pcd_mm": 60, "bolt_dia_mm": 8, "bolt_count": 4},
        "spur_gear": {"module_mm": 3, "teeth": 20, "face_width_mm": 20, "bore_dia_mm": 15},
        "shaft_basic": {"total_length_mm": 100, "shaft_dia_mm": 20},
        "shaft_with_keyway": {"total_length_mm": 100, "shaft_dia_mm": 20, "keyway_width_mm": 6, "keyway_depth_mm": 4},
    }
    params = dummy_params.get(recipe_name, {})
    return CADPartSpec(
        name="test_part",
        target_backend=[backend],
        features=[
            RecipeFeature(
                id="f1",
                type="recipe",
                recipe_name=recipe_name,
                parameters=params,
            )
        ],
    )


class TestCapabilityRegistry:
    def test_load_capability_registry_returns_all_backends(self):
        reg = load_capability_registry()
        assert "cadquery" in reg
        assert "solidworks2025" in reg
        assert "nx12" in reg
        assert "ansys181" in reg

    def test_cadquery_supports_flanged_hub(self):
        assert backend_supports_recipe("cadquery", "flanged_hub") is True

    def test_cadquery_no_longer_supports_spur_gear_recipe(self):
        # spur_gear is deprecated; must use involute_spur_gear primitive
        assert backend_supports_recipe("cadquery", "spur_gear") is False

    def test_solidworks_does_not_support_l_bracket(self):
        assert backend_supports_recipe("solidworks2025", "l_bracket") is False

    def test_nx_does_not_support_flanged_hub(self):
        assert backend_supports_recipe("nx12", "flanged_hub") is False

    def test_unknown_backend_returns_false(self):
        assert backend_supports_recipe("nonexistent", "box") is False

    def test_choose_backend_returns_cadquery_when_preferred_unsupported(self):
        spec = _make_spec("l_bracket", "solidworks2025")
        result = choose_backend(spec, preferred=["solidworks2025"])
        assert result.backend == "cadquery"  # fallback
        assert len(result.warnings) > 0

    def test_choose_backend_returns_preferred_when_supported(self):
        spec = _make_spec("block_with_hole", "nx12")
        result = choose_backend(spec, preferred=["nx12"])
        assert result.backend == "nx12"

    def test_choose_backend_returns_none_when_no_backend_supports(self):
        spec = CADPartSpec(
            name="test_unknown",
            target_backend=["cadquery"],
            features=[
                RecipeFeature(
                    id="f1",
                    type="recipe",
                    recipe_name="unknown_recipe_xyz",
                    parameters={},
                )
            ],
        )
        result = choose_backend(spec, preferred=["cadquery"])
        assert result.backend == "none"

    def test_list_backend_recipes_nx(self):
        recipes = list_backend_recipes("nx12")
        assert "block_with_hole" in recipes
        assert "l_bracket" in recipes
        assert "stepped_block" in recipes
        assert "flanged_hub" not in recipes
