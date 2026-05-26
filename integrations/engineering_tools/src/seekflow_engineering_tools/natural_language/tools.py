"""Natural-language CAD modelling tools — validate IR and build models."""

from __future__ import annotations

from seekflow import tool
from seekflow.types import ToolPolicy

from seekflow_engineering_tools.capabilities.registry import choose_backend, backend_supports_recipe
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.ir.cad import CADPartSpec


def build_natural_language_tools(config: EngineeringToolsConfig):
    """Build the natural language CAD-IR tools (always available)."""
    tools: list = []

    @tool(
        name="engineering_validate_cad_ir",
        description=(
            "Validate a CAD-IR specification against the schema, recipe "
            "registry, and capability registry. Returns normalized spec "
            "or detailed error list. Always call before engineering_build_cad_model."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def engineering_validate_cad_ir(spec: dict) -> dict:
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

    engineering_validate_cad_ir = engineering_validate_cad_ir.with_policy(
        ToolPolicy(
            capabilities={"cad.ir.read"},
            risk="read",
            timeout_s=30,
            parallel_safe=True,
        )
    )

    @tool(
        name="engineering_build_cad_model",
        description=(
            "Build a CAD model from a validated CAD-IR specification. "
            "Routes to the appropriate backend (cadquery, solidworks2025, nx12) "
            "and executes real geometry generation. Generates real STEP files. "
            "Validates output against spec expectations (bbox, body count, etc.)."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def engineering_build_cad_model(
        spec: dict,
        backend: str,
        out_step: str,
        inspect: bool = True,
        out_native: str | None = None,
    ) -> dict:
        try:
            cad_spec = CADPartSpec.model_validate(spec)

            # Pick the best backend
            selected = choose_backend(cad_spec, preferred=[backend])

            if selected == "cadquery":
                try:
                    from seekflow_engineering_tools.cadquery_backend.builder import (
                        build_cadquery_from_cad_ir,
                    )
                    return build_cadquery_from_cad_ir(
                        spec=cad_spec,
                        config=config,
                        out_step=out_step,
                        inspect=inspect,
                    )
                except Exception as exc:
                    return EngineeringActionResult(
                        ok=False,
                        software="cadquery",
                        action="build_cad_model",
                        error=f"CadQuery build failed: {exc}",
                    ).model_dump()

            elif selected == "solidworks2025":
                return EngineeringActionResult(
                    ok=False,
                    software="solidworks",
                    action="build_cad_model",
                    error=(
                        "SolidWorks backend selected but engineering_build_cad_model "
                        "cannot drive SolidWorks COM directly. Use solidworks_create_* tools "
                        "for SolidWorks builds."
                    ),
                    metrics={
                        "backend_used": "solidworks2025",
                        "feature_count": len(cad_spec.features),
                    },
                    warnings=[
                        "SolidWorks requires direct COM automation. "
                        "Use solidworks_create_flanged_hub_part or "
                        "solidworks_create_spur_gear_part tools."
                    ],
                ).model_dump()

            elif selected == "nx12":
                return EngineeringActionResult(
                    ok=False,
                    software="nx",
                    action="build_cad_model",
                    error=(
                        "NX 12.0 backend selected but engineering_build_cad_model "
                        "cannot drive NX bridge directly. Use nx_create_* tools "
                        "for NX builds."
                    ),
                    metrics={
                        "backend_used": "nx12",
                        "feature_count": len(cad_spec.features),
                    },
                    warnings=[
                        "NX 12.0 requires the bridge journal running inside NX. "
                        "Use nx_create_block_with_hole, nx_create_l_bracket, "
                        "or nx_create_stepped_block tools."
                    ],
                ).model_dump()

            else:
                return EngineeringActionResult(
                    ok=False,
                    software="generic",
                    action="build_cad_model",
                    error=f"No suitable backend found. Tried: {backend}, got: {selected}",
                ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="generic",
                action="build_cad_model",
                error=str(exc),
            ).model_dump()

    engineering_build_cad_model = engineering_build_cad_model.with_policy(
        ToolPolicy(
            capabilities={"cad.ir.write", "cad.cadquery.write", "filesystem.write"},
            risk="write",
            timeout_s=180,
            workspace_root=config.workspace_root,
            path_params=frozenset({"out_step", "out_native"}),
            parallel_safe=False,
            requires_approval=False,
            idempotent=False,
        )
    )

    tools.extend([
        engineering_validate_cad_ir,
        engineering_build_cad_model,
    ])
    return tools
