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


def normalize_recipe_parameters(recipe_name: str, parameters: dict) -> dict:
    """Normalize and validate recipe parameters.

    - Fill defaults
    - Type coercion (float, int, str, bool)
    - Min/max validation
    - Cross-parameter geometry constraints

    Returns normalized parameter dict.
    Raises ValueError if validation fails.
    """
    rd = get_recipe_definition(recipe_name)
    if rd is None:
        raise ValueError(f"Unknown recipe: '{recipe_name}'. Available: {list_recipe_names()}")

    errors: list[str] = []
    schema_params = {p.name: p for p in rd.parameters}
    normalized: dict = {}

    # Check for unknown parameters
    for key in parameters:
        if key not in schema_params:
            errors.append(
                f"Unknown parameter '{key}' for recipe '{recipe_name}'. "
                f"Allowed: {sorted(schema_params.keys())}"
            )

    for pname, pinfo in schema_params.items():
        if pname in parameters:
            value = parameters[pname]
            expected_type = pinfo.type

            # Type coercion
            try:
                if expected_type == "float":
                    if isinstance(value, bool):
                        errors.append(f"Parameter '{pname}' must be float, got bool")
                        continue
                    normalized[pname] = float(value)
                elif expected_type == "int":
                    if isinstance(value, bool):
                        errors.append(f"Parameter '{pname}' must be int, got bool")
                        continue
                    normalized[pname] = int(value)
                elif expected_type == "str":
                    normalized[pname] = str(value)
                elif expected_type == "bool":
                    normalized[pname] = bool(value)
            except (TypeError, ValueError):
                errors.append(f"Parameter '{pname}' must be {expected_type}, got {type(value).__name__}: {value}")
                continue

            # Min/max validation
            if expected_type in ("float", "int") and not isinstance(value, bool):
                v = float(normalized[pname])
                if pinfo.min_value is not None and v < pinfo.min_value:
                    errors.append(f"Parameter '{pname}' value {v} < min {pinfo.min_value}")
                if pinfo.max_value is not None and v > pinfo.max_value:
                    errors.append(f"Parameter '{pname}' value {v} > max {pinfo.max_value}")

        elif pinfo.required:
            errors.append(f"Missing required parameter '{pname}' for recipe '{recipe_name}'")
        elif pinfo.default is not None:
            normalized[pname] = pinfo.default

    if errors:
        raise ValueError("; ".join(errors))

    # Cross-parameter geometry constraints
    _apply_geometry_constraints(recipe_name, normalized)

    return normalized


def _apply_geometry_constraints(recipe_name: str, params: dict) -> None:
    """Check cross-parameter geometry constraints."""
    if recipe_name == "flanged_hub":
        if params.get("flange_dia_mm", 0) <= params.get("hub_dia_mm", 0):
            raise ValueError("flange_dia_mm must be > hub_dia_mm")
        if params.get("hub_dia_mm", 0) <= params.get("bore_dia_mm", 0):
            raise ValueError("hub_dia_mm must be > bore_dia_mm")
        if int(params.get("bolt_count", 0)) < 3:
            raise ValueError("bolt_count must be >= 3")
        if params.get("bolt_pcd_mm", 0) >= params.get("flange_dia_mm", 1):
            raise ValueError("bolt_pcd_mm must be < flange_dia_mm")
        if params.get("bolt_pcd_mm", 0) <= params.get("hub_dia_mm", 0):
            raise ValueError("bolt_pcd_mm must be > hub_dia_mm")
    elif recipe_name == "spur_gear":
        if params.get("module_mm", 0) <= 0:
            raise ValueError("module_mm must be > 0")
        if int(params.get("teeth", 0)) < 6:
            raise ValueError("teeth must be >= 6")
        if params.get("face_width_mm", 0) <= 0:
            raise ValueError("face_width_mm must be > 0")
        if params.get("bore_dia_mm", 0) <= 0:
            raise ValueError("bore_dia_mm must be > 0")
    elif recipe_name == "block_with_hole":
        length = params.get("length_mm", 0)
        width = params.get("width_mm", 0)
        hole = params.get("hole_dia_mm", 0)
        if hole >= min(length, width):
            raise ValueError(f"hole_dia_mm ({hole}) must be < min(length_mm, width_mm) = {min(length, width)}")
    elif recipe_name == "l_bracket":
        if params.get("thickness_mm", 0) <= 0:
            raise ValueError("thickness_mm must be > 0")
        if params.get("leg_height_mm", 0) <= 0:
            raise ValueError("leg_height_mm must be > 0")
    elif recipe_name == "stepped_block":
        if params.get("top_length_mm", 0) > params.get("base_length_mm", 1):
            raise ValueError("top_length_mm must be <= base_length_mm")
        if params.get("top_width_mm", 0) > params.get("base_width_mm", 1):
            raise ValueError("top_width_mm must be <= base_width_mm")
