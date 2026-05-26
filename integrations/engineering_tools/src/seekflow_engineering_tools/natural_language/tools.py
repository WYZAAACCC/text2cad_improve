"""Natural-language CAD modelling tools — validate IR and build models."""

from __future__ import annotations

from pathlib import Path

from seekflow_engineering_tools.capabilities.registry import choose_backend
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.ir.cad import CADPartSpec


def engineering_validate_cad_ir(spec: dict) -> dict:
    """Validate a CAD-IR dict against Pydantic schema.

    Checks feature uniqueness, backend capability, recipe parameters.
    Returns normalized spec or error list.
    """
    try:
        normalized = CADPartSpec.model_validate(spec)
        errors: list[str] = []

        # Check for unsupported recipes on target backends
        for backend in normalized.target_backend:
            from seekflow_engineering_tools.capabilities.registry import (
                backend_supports_recipe,
            )
            for feat in normalized.features:
                if feat.type == "recipe":
                    if not backend_supports_recipe(backend, feat.recipe_name):
                        errors.append(
                            f"Recipe '{feat.recipe_name}' not available for backend '{backend}'"
                        )

        return EngineeringActionResult(
            ok=len(errors) == 0,
            software="generic",
            action="validate_cad_ir",
            message=(
                "CAD-IR validation passed."
                if not errors
                else f"CAD-IR validation found {len(errors)} issue(s)."
            ),
            metrics={
                "normalized_spec": normalized.model_dump(exclude_defaults=True),
                "feature_count": len(normalized.features),
                "target_backend": normalized.target_backend,
            },
            warnings=errors if errors else [],
        ).model_dump()

    except Exception as exc:
        return EngineeringActionResult(
            ok=False,
            software="generic",
            action="validate_cad_ir",
            error=str(exc),
        ).model_dump()


def engineering_build_cad_model(
    spec: dict,
    backend: str,
    out_native: str | None = None,
    out_step: str | None = None,
    inspect: bool = True,
) -> dict:
    """Build a CAD model from a CAD-IR spec using the specified backend.

    Routes to the appropriate backend compiler (cadquery, solidworks2025, nx12).
    Falls back to cadquery if the target backend doesn't support the recipe.
    """
    try:
        cad_spec = CADPartSpec.model_validate(spec)

        # Pick the best backend
        selected = choose_backend(cad_spec, preferred=[backend])

        if selected == "cadquery":
            try:
                from seekflow_engineering_tools.cadquery_backend.compiler import (
                    compile_cad_ir_to_cadquery_script,
                )
                script = compile_cad_ir_to_cadquery_script(cad_spec, out_step=out_step)
                return EngineeringActionResult(
                    ok=True,
                    software="cadquery",
                    action="build_cad_model",
                    message=f"CadQuery script compiled ({len(script)} chars).",
                    metrics={
                        "backend_used": "cadquery",
                        "script_length": len(script),
                        "feature_count": len(cad_spec.features),
                    },
                    files_created=[out_step] if out_step else [],
                ).model_dump()
            except Exception as exc:
                return EngineeringActionResult(
                    ok=False,
                    software="cadquery",
                    action="build_cad_model",
                    error=f"CadQuery compilation failed: {exc}",
                ).model_dump()

        elif selected == "solidworks2025":
            # For SolidWorks, delegate to the specific tool functions
            # This is a routing layer — actual SW calls happen in solidworks/tools.py
            return EngineeringActionResult(
                ok=True,
                software="solidworks",
                action="build_cad_model",
                message="Routed to SolidWorks 2025 backend. Use solidworks_create_* tools directly.",
                metrics={
                    "backend_used": "solidworks2025",
                    "feature_count": len(cad_spec.features),
                },
            ).model_dump()

        elif selected == "nx12":
            return EngineeringActionResult(
                ok=True,
                software="nx",
                action="build_cad_model",
                message="Routed to NX 12.0 backend. Use nx_create_* tools directly.",
                metrics={
                    "backend_used": "nx12",
                    "feature_count": len(cad_spec.features),
                },
            ).model_dump()

        else:
            return EngineeringActionResult(
                ok=False,
                software="generic",
                action="build_cad_model",
                error=f"No suitable backend for: {backend}",
            ).model_dump()

    except Exception as exc:
        return EngineeringActionResult(
            ok=False,
            software="generic",
            action="build_cad_model",
            error=str(exc),
        ).model_dump()
