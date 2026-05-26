from __future__ import annotations

from seekflow_engineering_tools.recipes.base import RecipeDefinition, RecipeParameter
from seekflow_engineering_tools.recipes.mechanical import MECHANICAL_RECIPES

RECIPE_REGISTRY: dict[str, RecipeDefinition] = {}

for r in MECHANICAL_RECIPES:
    RECIPE_REGISTRY[r.name] = r


def list_recipe_names() -> list[str]:
    return sorted(RECIPE_REGISTRY.keys())


def get_recipe_definition(name: str) -> RecipeDefinition | None:
    return RECIPE_REGISTRY.get(name)


def recipe_supports_backend(recipe_name: str, backend: str) -> bool:
    rd = get_recipe_definition(recipe_name)
    if rd is None:
        return False
    return backend in rd.supported_backends
