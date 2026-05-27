"""Natural-language CAD modelling tools — validate IR and build models."""

from __future__ import annotations

from pathlib import Path

from seekflow import tool
from seekflow.types import ToolPolicy

from seekflow_engineering_tools.capabilities.registry import (
    BackendChoice,
    backend_supports_feature,
    choose_backend,
    get_primitive_strategy,
)
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_extension, ensure_inside_workspace
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.ir.cad import CADPartSpec
from seekflow_engineering_tools.natural_language.normalizer import (
    detect_ambiguities,
    rewrite_deprecated_recipes_to_primitives,
)
from seekflow_engineering_tools.recipes.registry import normalize_recipe_parameters


def build_natural_language_tools(config: EngineeringToolsConfig):
    """Build the natural language CAD-IR tools (always available)."""
    tools: list = []

    @tool(
        name="engineering_validate_cad_ir",
        description=(
            "Validate a CAD-IR specification against the schema, recipe "
            "registry, primitive registry, and capability registry. "
            "Returns normalized spec or detailed error list. "
            "Always call before engineering_build_cad_model."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def engineering_validate_cad_ir(spec: dict) -> dict:
        try:
            # Step 0: Rewrite deprecated recipes to primitives — must NOT swallow errors
            rewrite_warnings: list[str] = []
            try:
                spec = rewrite_deprecated_recipes_to_primitives(spec)
                rewrite_warnings = spec.pop("rewrite_warnings", [])
            except Exception as exc:
                return EngineeringActionResult(
                    ok=False,
                    software="generic",
                    action="validate_cad_ir",
                    error=f"Deprecated recipe rewrite failed: {exc}",
                ).model_dump()

            # Step 1: Schema validation
            normalized = CADPartSpec.model_validate(spec)
            errors: list[str] = []
            warnings: list[str] = list(rewrite_warnings)

            # Step 2: Detect ambiguities in user intent
            ambiguities = detect_ambiguities({
                "parameters": normalized.parameters,
                "suggested_template": next(
                    (f.recipe_name for f in normalized.features if f.type == "recipe"), None
                ),
            })

            # Step 3: Normalize recipe AND primitive parameters
            from seekflow_engineering_tools.geometry_primitives.registry import (
                normalize_primitive_parameters,
            )
            normalized_params: dict = {}
            for idx, feat in enumerate(normalized.features):
                try:
                    if feat.type == "recipe":
                        n = normalize_recipe_parameters(feat.recipe_name, feat.parameters)
                        feat.parameters = n
                    elif feat.type == "primitive":
                        n = normalize_primitive_parameters(feat.primitive_name, feat.parameters)
                        feat.parameters = n
                    else:
                        continue
                    normalized_params[feat.id] = n
                except ValueError as exc:
                    errors.append(f"Feature '{feat.id}': {exc}")

            # Step 4: Check backend support for ALL features (recipe + primitive)
            for backend in normalized.target_backend:
                for feat in normalized.features:
                    if not backend_supports_feature(backend, feat):
                        errors.append(
                            f"Feature '{feat.id}' (type={feat.type}) "
                            f"not supported by backend '{backend}'"
                        )

            metrics: dict = {
                "feature_count": len(normalized.features),
                "target_backend": normalized.target_backend,
                "ambiguities": ambiguities["ambiguities"],
                "suggested_template": ambiguities["suggested_template"],
            }
            if normalized_params:
                metrics["normalized_parameters"] = normalized_params
            # Include full normalized spec in metrics
            try:
                metrics["normalized_spec"] = normalized.model_dump()
            except Exception:
                pass

            return EngineeringActionResult(
                ok=len(errors) == 0,
                software="generic",
                action="validate_cad_ir",
                message=(
                    "CAD-IR validation passed."
                    if not errors
                    else f"CAD-IR validation found {len(errors)} issue(s)."
                ),
                metrics=metrics,
                warnings=warnings + errors if errors else warnings,
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
            "Routes to the appropriate backend based on feature types "
            "and primitive strategies. For gear primitives on SW/NX, "
            "first builds canonical STEP via CadQuery/CQ_Gears, then imports."
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
        allow_backend_fallback: bool = False,
    ) -> dict:
        try:
            # Step 0: Internal normalize — rewrite deprecated, normalize params
            spec = rewrite_deprecated_recipes_to_primitives(spec)
            spec.pop("rewrite_warnings", None)

            cad_spec = CADPartSpec.model_validate(spec)

            from seekflow_engineering_tools.geometry_primitives.registry import (
                normalize_primitive_parameters,
            )
            for feat in cad_spec.features:
                if feat.type == "recipe":
                    feat.parameters = normalize_recipe_parameters(feat.recipe_name, feat.parameters)
                elif feat.type == "primitive":
                    feat.parameters = normalize_primitive_parameters(feat.primitive_name, feat.parameters)

            # Reject legacy spur_gear recipe in engineering builds
            for feat in cad_spec.features:
                if feat.type == "recipe" and feat.recipe_name == "spur_gear":
                    return EngineeringActionResult(
                        ok=False,
                        software="generic",
                        action="build_cad_model",
                        error=(
                            "Recipe 'spur_gear' is deprecated for engineering builds. "
                            "Use primitive 'involute_spur_gear' instead."
                        ),
                    ).model_dump()

            choice: BackendChoice = choose_backend(cad_spec, preferred=[backend])

            # Disallow silent fallback from solidworks2025/nx12 to cadquery
            if backend in {"solidworks2025", "nx12"} and choice.backend == "cadquery" and not allow_backend_fallback:
                return EngineeringActionResult(
                    ok=False,
                    software="generic",
                    action="build_cad_model",
                    error=(
                        f"Requested backend '{backend}' does not support this spec "
                        f"and fallback is not allowed. Use allow_backend_fallback=True "
                        f"or switch to cadquery explicitly."
                    ),
                    warnings=choice.warnings,
                ).model_dump()

            # ── cadquery: always native build ──
            if choice.backend == "cadquery":
                from seekflow_engineering_tools.cadquery_backend.builder import (
                    build_cadquery_from_cad_ir,
                )
                result = build_cadquery_from_cad_ir(
                    spec=cad_spec,
                    config=config,
                    out_step=out_step,
                    inspect=inspect,
                )
                if choice.warnings:
                    result.setdefault("warnings", []).extend(choice.warnings)
                return result

            # ── solidworks2025 / nx12: check for primitives ──
            if choice.backend in {"solidworks2025", "nx12"}:
                primitive_features = [f for f in cad_spec.features if f.type == "primitive"]

                if primitive_features:
                    # Verify all primitives use cadquery_step_import strategy
                    for f in primitive_features:
                        strategy = get_primitive_strategy(choice.backend, f.primitive_name)
                        if strategy != "cadquery_step_import":
                            return EngineeringActionResult(
                                ok=False, software=choice.backend,
                                action="build_cad_model",
                                error=(
                                    f"Primitive '{f.primitive_name}' has strategy "
                                    f"'{strategy}' on '{choice.backend}', "
                                    f"expected 'cadquery_step_import'."
                                ),
                            ).model_dump()

                    # Route through canonical STEP import
                    from seekflow_engineering_tools.natural_language.backend_builders import (
                        build_solidworks_from_canonical_step,
                        build_nx_from_canonical_step,
                    )
                    if choice.backend == "solidworks2025":
                        return build_solidworks_from_canonical_step(
                            cad_spec, config, out_step, out_native, inspect)
                    elif choice.backend == "nx12":
                        return build_nx_from_canonical_step(
                            cad_spec, config, out_step, out_native, inspect)

                # No primitives: use legacy recipe-only path
                from seekflow_engineering_tools.natural_language.backend_builders import (
                    build_solidworks_direct_recipe,
                    build_nx_direct_recipe,
                )
                if choice.backend == "solidworks2025":
                    return build_solidworks_direct_recipe(cad_spec, config, out_step)
                elif choice.backend == "nx12":
                    return build_nx_direct_recipe(cad_spec, config, out_step)

            # ── No backend ──
            return EngineeringActionResult(
                ok=False,
                software="generic",
                action="build_cad_model",
                error=f"No suitable backend found. Tried: {backend}, got: {choice.backend}",
                warnings=choice.warnings,
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
            capabilities={"cad.ir.write", "cad.cadquery.write", "filesystem.write",
                         "cad.solidworks.write", "cad.nx.write"},
            risk="write",
            timeout_s=300,
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
