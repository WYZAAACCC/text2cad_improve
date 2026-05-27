"""Natural-language CAD modelling tools — validate IR and build models."""

from __future__ import annotations

from pathlib import Path

from seekflow import tool
from seekflow.types import ToolPolicy

from seekflow_engineering_tools.capabilities.registry import (
    BackendChoice,
    choose_backend,
)
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_extension, ensure_inside_workspace
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.ir.cad import CADPartSpec
from seekflow_engineering_tools.natural_language.normalizer import detect_ambiguities
from seekflow_engineering_tools.natural_language.prompts import NL_CAD_SYSTEM_PROMPT
from seekflow_engineering_tools.recipes.registry import normalize_recipe_parameters


def _build_solidworks_from_spec(spec: CADPartSpec, config: EngineeringToolsConfig, out_step: str) -> dict:
    """Execute a single-recipe build via SolidWorks COM."""
    recipe_feat = next(f for f in spec.features if f.type == "recipe")
    params = normalize_recipe_parameters(recipe_feat.recipe_name, recipe_feat.parameters)

    workspace = config.workspace_root
    step_path = ensure_inside_workspace(workspace, out_step)
    ensure_extension(step_path, {".step", ".stp"})
    step_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate SLDPRT path
    sldprt_path = step_path.with_suffix(".sldprt")
    ensure_extension(sldprt_path, {".sldprt"})

    if sldprt_path.exists() and not config.allow_overwrite:
        return EngineeringActionResult(
            ok=False, software="solidworks", action="build_cad_model",
            error=f"Output file {sldprt_path} already exists.",
        ).model_dump()

    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient

    client = SolidWorksClient(
        visible=config.solidworks_visible,
        part_template=config.solidworks_part_template,
    ).connect()
    model = client.new_part()

    name = recipe_feat.recipe_name
    if name == "box":
        client.create_extruded_box(
            model,
            length_m=params["length_mm"] / 1000.0,
            width_m=params["width_mm"] / 1000.0,
            height_m=params["height_mm"] / 1000.0,
        )
    elif name == "flanged_hub":
        client.create_flanged_hub(
            model,
            flange_dia_m=params["flange_dia_mm"] / 1000.0,
            flange_h_m=params["flange_thickness_mm"] / 1000.0,
            hub_dia_m=params["hub_dia_mm"] / 1000.0,
            hub_h_m=params["hub_height_mm"] / 1000.0,
            bore_dia_m=params["bore_dia_mm"] / 1000.0,
            bolt_pcd_m=params["bolt_pcd_mm"] / 1000.0,
            bolt_dia_m=params["bolt_dia_mm"] / 1000.0,
            bolt_count=int(params["bolt_count"]),
        )
    elif name == "spur_gear":
        client.create_spur_gear(
            model,
            module_m=params["module_mm"] / 1000.0,
            teeth=int(params["teeth"]),
            face_width_m=params["face_width_mm"] / 1000.0,
            bore_dia_m=params["bore_dia_mm"] / 1000.0,
        )
    else:
        return EngineeringActionResult(
            ok=False, software="solidworks", action="build_cad_model",
            error=f"SolidWorks backend does not support recipe '{name}' for direct build.",
        ).model_dump()

    if not client.save_as(model, sldprt_path):
        return EngineeringActionResult(
            ok=False, software="solidworks", action="build_cad_model",
            error=f"SolidWorks SaveAs failed for {sldprt_path}",
        ).model_dump()

    files_created = [str(sldprt_path)]

    if not client.export_step(model, step_path):
        return EngineeringActionResult(
            ok=False, software="solidworks", action="build_cad_model",
            error=f"SolidWorks STEP export failed for {step_path}",
        ).model_dump()
    files_created.append(str(step_path))

    return EngineeringActionResult(
        ok=True, software="solidworks", action="build_cad_model",
        message=f"SolidWorks part built: {sldprt_path}",
        files_created=files_created,
        metrics={"recipe": name, "backend": "solidworks2025"},
    ).model_dump()


def _build_nx_from_spec(spec: CADPartSpec, config: EngineeringToolsConfig, out_step: str) -> dict:
    """Execute a single-recipe build via NX job queue."""
    recipe_feat = next(f for f in spec.features if f.type == "recipe")
    params = normalize_recipe_parameters(recipe_feat.recipe_name, recipe_feat.parameters)

    workspace = config.workspace_root
    step_path = ensure_inside_workspace(workspace, out_step)
    ensure_extension(step_path, {".step", ".stp"})
    step_path.parent.mkdir(parents=True, exist_ok=True)

    prt_path = step_path.with_suffix(".prt")
    ensure_extension(prt_path, {".prt"})

    job_root = config.nx_job_root or (workspace / "nx_jobs")

    from seekflow_engineering_tools.nx.job_queue import NXJobQueue

    name = recipe_feat.recipe_name
    action_map = {
        "box": "create_block_part",
        "block_with_hole": "create_block_with_hole",
        "l_bracket": "create_l_bracket",
        "stepped_block": "create_stepped_block",
    }
    action = action_map.get(name)
    if action is None:
        return EngineeringActionResult(
            ok=False, software="nx", action="build_cad_model",
            error=f"NX backend does not support recipe '{name}' for direct build.",
        ).model_dump()

    # Map recipe params to NX action params
    nx_params: dict = {"out_prt": str(prt_path), "out_step": str(step_path)}
    if name == "box":
        nx_params.update({
            "length_mm": params["length_mm"],
            "width_mm": params["width_mm"],
            "height_mm": params["height_mm"],
        })
    elif name == "block_with_hole":
        nx_params.update({
            "length_mm": params["length_mm"],
            "width_mm": params["width_mm"],
            "height_mm": params["height_mm"],
            "hole_dia_mm": params["hole_dia_mm"],
        })
        if "hole_x_mm" in params:
            nx_params["hole_x"] = params["hole_x_mm"]
        if "hole_z_mm" in params:
            nx_params["hole_z"] = params["hole_z_mm"]
    elif name == "l_bracket":
        nx_params.update({
            "base_length": params["base_length_mm"],
            "base_width": params["base_width_mm"],
            "thickness": params["thickness_mm"],
            "leg_height": params["leg_height_mm"],
        })
    elif name == "stepped_block":
        nx_params.update({
            "base_length": params["base_length_mm"],
            "base_width": params["base_width_mm"],
            "base_height": params["base_height_mm"],
            "top_length": params["top_length_mm"],
            "top_width": params["top_width_mm"],
            "top_height": params["top_height_mm"],
        })

    q = NXJobQueue(job_root)
    job_id = q.submit(action, nx_params)
    try:
        result = q.wait(job_id, timeout_s=config.nx_default_timeout_s)
    except TimeoutError:
        return EngineeringActionResult(
            ok=False, software="nx", action="build_cad_model",
            error=f"NX job {job_id} timed out after {config.nx_default_timeout_s}s.",
        ).model_dump()

    return EngineeringActionResult(
        ok=bool(result.get("ok")),
        software="nx",
        action="build_cad_model",
        message=result.get("message", ""),
        files_created=result.get("files_created", []),
        metrics={**result.get("metrics", {}), "backend": "nx12", "recipe": name},
        error=result.get("error"),
    ).model_dump()


def build_natural_language_tools(config: EngineeringToolsConfig):
    """Build the natural language CAD-IR tools (always available)."""
    tools: list = []

    @tool(
        name="engineering_validate_cad_ir",
        description=(
            "Validate a CAD-IR specification against the schema, recipe "
            "registry, and capability registry. Returns normalized spec "
            "or detailed error list. Always call before engineering_build_cad_model. "
            "System prompt: " + NL_CAD_SYSTEM_PROMPT[:200] + "..."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def engineering_validate_cad_ir(spec: dict) -> dict:
        try:
            normalized = CADPartSpec.model_validate(spec)
            errors: list[str] = []

            # Detect ambiguities in user intent
            ambiguities = detect_ambiguities({
                "parameters": normalized.parameters,
                "suggested_template": next(
                    (f.recipe_name for f in normalized.features if f.type == "recipe"), None
                ),
            })

            # Normalize recipe parameters
            normalized_params: dict = {}
            for feat in normalized.features:
                if feat.type == "recipe":
                    try:
                        n = normalize_recipe_parameters(feat.recipe_name, feat.parameters)
                        normalized_params[feat.id] = n
                    except ValueError as e:
                        errors.append(f"Feature '{feat.id}': {e}")

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

            metrics: dict = {
                "feature_count": len(normalized.features),
                "target_backend": normalized.target_backend,
                "ambiguities": ambiguities["ambiguities"],
                "suggested_template": ambiguities["suggested_template"],
            }
            if normalized_params:
                metrics["normalized_parameters"] = normalized_params

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
            choice: BackendChoice = choose_backend(cad_spec, preferred=[backend])

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

            elif choice.backend == "solidworks2025":
                return _build_solidworks_from_spec(cad_spec, config, out_step)

            elif choice.backend == "nx12":
                return _build_nx_from_spec(cad_spec, config, out_step)

            else:
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
            capabilities={"cad.ir.write", "cad.cadquery.write", "filesystem.write", "cad.solidworks.write", "cad.nx.write"},
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
