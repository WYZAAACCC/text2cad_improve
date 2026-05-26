"""Validation utilities for CAD-IR and CAE-IR."""

from __future__ import annotations

from seekflow_engineering_tools.ir.cad import CADPartSpec


def validate_cad_ir(spec: dict) -> tuple[CADPartSpec, list[str]]:
    """Validate a raw dict against CADPartSpec. Returns (normalized, errors)."""
    errors: list[str] = []
    try:
        normalized = CADPartSpec.model_validate(spec)
        return normalized, errors
    except Exception as exc:
        errors.append(str(exc))
        return None, errors  # type: ignore[return-value]


def check_backend_capability(spec: CADPartSpec, backend: str, capabilities: dict) -> list[str]:
    """Check if a spec's features are all supported by the target backend."""
    errors: list[str] = []
    stable_recipes = set(capabilities.get("stable_recipes", []))

    for feat in spec.features:
        if feat.type == "recipe":
            if feat.recipe_name not in stable_recipes:
                errors.append(
                    f"Recipe '{feat.recipe_name}' not in backend '{backend}' stable recipes. "
                    f"Available: {sorted(stable_recipes)}"
                )
    return errors
