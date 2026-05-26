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


def get_recipe(name: str) -> RecipeDefinition | None:
    """Alias for get_recipe_definition."""
    return RECIPE_REGISTRY.get(name)


def recipe_supports_backend(recipe_name: str, backend: str) -> bool:
    rd = get_recipe_definition(recipe_name)
    if rd is None:
        return False
    return backend in rd.supported_backends


def validate_recipe_parameters(recipe_name: str, parameters: dict) -> list[str]:
    """Validate parameters against a recipe definition.

    Checks: unknown params, required params, type coercion, min/max.
    Returns a list of error strings (empty = valid).
    """
    rd = get_recipe_definition(recipe_name)
    if rd is None:
        return [f"Unknown recipe: '{recipe_name}'. Available: {list_recipe_names()}"]

    errors: list[str] = []
    schema_params = {p.name: p for p in rd.parameters}

    # Check for unknown parameters
    for key in parameters:
        if key not in schema_params:
            errors.append(
                f"Unknown parameter '{key}' for recipe '{recipe_name}'. "
                f"Allowed: {sorted(schema_params.keys())}"
            )

    # Check required params and validate type/min/max
    for pname, pinfo in schema_params.items():
        if pname in parameters:
            value = parameters[pname]
            expected_type = pinfo.type

            # Type checking and coercion
            if expected_type == "float":
                try:
                    float(value)
                except (TypeError, ValueError):
                    errors.append(
                        f"Parameter '{pname}' must be float, got {type(value).__name__}: {value}"
                    )
            elif expected_type == "int":
                try:
                    int(value)
                except (TypeError, ValueError):
                    errors.append(
                        f"Parameter '{pname}' must be int, got {type(value).__name__}: {value}"
                    )
                if isinstance(value, bool):
                    errors.append(
                        f"Parameter '{pname}' must be int, got bool: {value}"
                    )
            elif expected_type == "str":
                if not isinstance(value, str):
                    errors.append(
                        f"Parameter '{pname}' must be str, got {type(value).__name__}: {value}"
                    )
            elif expected_type == "bool":
                if not isinstance(value, bool):
                    errors.append(
                        f"Parameter '{pname}' must be bool, got {type(value).__name__}: {value}"
                    )

            # Min/max validation for numeric types
            if expected_type in ("float", "int") and not isinstance(value, bool):
                v = float(value)
                if pinfo.min_value is not None and v < pinfo.min_value:
                    errors.append(
                        f"Parameter '{pname}' value {v} < min {pinfo.min_value}"
                    )
                if pinfo.max_value is not None and v > pinfo.max_value:
                    errors.append(
                        f"Parameter '{pname}' value {v} > max {pinfo.max_value}"
                    )

        elif pinfo.required:
            errors.append(f"Missing required parameter '{pname}' for recipe '{recipe_name}'")

    return errors
