"""Test recipe registry completeness."""

from seekflow_engineering_tools.recipes.registry import (
    list_recipe_names,
    get_recipe_definition,
    recipe_supports_backend,
)


class TestRecipeRegistry:
    def test_registry_knows_core_recipes(self):
        names = set(list_recipe_names())
        assert "flanged_hub" in names
        assert "l_bracket" in names
        assert "block_with_hole" in names
        assert "stepped_block" in names
        assert "spur_gear" in names
        assert "box" in names
        assert "cylinder" in names
        assert "shaft_basic" in names
        assert "shaft_with_keyway" in names

    def test_registry_has_ten_recipes_minimum(self):
        names = list_recipe_names()
        assert len(names) >= 10

    def test_get_recipe_definition(self):
        rd = get_recipe_definition("flanged_hub")
        assert rd is not None
        assert rd.name == "flanged_hub"
        assert rd.category == "mechanical"

    def test_get_nonexistent_recipe(self):
        assert get_recipe_definition("nonexistent") is None

    def test_recipe_supports_backend(self):
        assert recipe_supports_backend("flanged_hub", "solidworks2025") is True
        assert recipe_supports_backend("flanged_hub", "cadquery") is True
        assert recipe_supports_backend("flanged_hub", "nx12") is False

    def test_l_bracket_supports_nx(self):
        assert recipe_supports_backend("l_bracket", "nx12") is True

    def test_box_supports_all_three(self):
        assert recipe_supports_backend("box", "solidworks2025") is True
        assert recipe_supports_backend("box", "nx12") is True
        assert recipe_supports_backend("box", "cadquery") is True

    def test_flanged_hub_has_validation_defaults(self):
        rd = get_recipe_definition("flanged_hub")
        assert rd is not None
        assert rd.validation_defaults.get("expected_body_count") == 1
        assert rd.validation_defaults.get("expected_through_hole_count") == 5

    def test_all_recipes_have_parameters(self):
        for name in list_recipe_names():
            rd = get_recipe_definition(name)
            assert rd is not None, f"Recipe '{name}' missing"
            assert len(rd.parameters) > 0, f"Recipe '{name}' has no params"
            assert rd.supported_backends, f"Recipe '{name}' has no backends"
