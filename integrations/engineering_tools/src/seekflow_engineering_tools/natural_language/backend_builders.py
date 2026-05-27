"""Unified build planner for engineering backends.

Routes CAD-IR features through the appropriate build strategy:
- cadquery: native CadQuery build (recipes + primitives)
- solidworks2025: recipe direct for box/flanged_hub; STEP import for gear primitives
- nx12: recipe direct for box/block_with_hole/l_bracket/stepped_block; STEP import for gear primitives
"""

from __future__ import annotations

from pathlib import Path

from seekflow_engineering_tools.capabilities.registry import get_primitive_strategy
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_extension, ensure_inside_workspace
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.ir.cad import CADPartSpec


def spec_has_primitives(spec: CADPartSpec) -> bool:
    return any(f.type == "primitive" for f in spec.features)


def get_single_primitive_name(spec: CADPartSpec) -> str | None:
    primitives = [f for f in spec.features if f.type == "primitive"]
    if len(primitives) == 1:
        return primitives[0].primitive_name
    return None


# ── Canonical STEP via CadQuery/CQ_Gears ────────────────────────────────────


def build_canonical_step_with_cadquery(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_step: str | Path,
    inspect: bool = True,
) -> dict:
    """Build canonical STEP via CadQuery (with CQ_Gears for gear primitives).

    This is the mandatory first step for all primitive builds, regardless of
    final target backend. SolidWorks and NX import this STEP file.
    """
    from seekflow_engineering_tools.cadquery_backend.builder import (
        build_cadquery_from_cad_ir,
    )

    return build_cadquery_from_cad_ir(
        spec=spec,
        config=config,
        out_step=str(out_step),
        inspect=inspect,
    )


# ── SolidWorks ─────────────────────────────────────────────────────────────


def build_solidworks_direct_recipe(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_step: str,
) -> dict:
    """Build simple box or flanged_hub recipe directly in SolidWorks.

    Only supports: box, flanged_hub.
    spur_gear is explicitly rejected — must use primitive + STEP import.
    """
    recipe_feats = [f for f in spec.features if f.type == "recipe"]
    if not recipe_feats:
        return EngineeringActionResult(
            ok=False, software="solidworks", action="build_direct_recipe",
            error="No recipe features found for SolidWorks direct build.",
        ).model_dump()

    recipe_feat = recipe_feats[0]
    name = recipe_feat.recipe_name

    if name not in ("box", "flanged_hub"):
        return EngineeringActionResult(
            ok=False, software="solidworks", action="build_direct_recipe",
            error=(
                f"Recipe '{name}' is not supported for SolidWorks direct build. "
                f"Only 'box' and 'flanged_hub' are available. "
                f"For gears, use primitive 'involute_spur_gear'."
            ),
        ).model_dump()

    from seekflow_engineering_tools.recipes.registry import normalize_recipe_parameters
    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient

    params = normalize_recipe_parameters(name, recipe_feat.parameters)
    workspace = config.workspace_root

    step_path = ensure_inside_workspace(workspace, out_step)
    ensure_extension(step_path, {".step", ".stp"})
    step_path.parent.mkdir(parents=True, exist_ok=True)

    sldprt_path = step_path.with_suffix(".sldprt")
    ensure_extension(sldprt_path, {".sldprt"})

    if sldprt_path.exists() and not config.allow_overwrite:
        return EngineeringActionResult(
            ok=False, software="solidworks", action="build_direct_recipe",
            error=f"Output file {sldprt_path} already exists.",
        ).model_dump()

    client = SolidWorksClient(
        visible=config.solidworks_visible,
        part_template=config.solidworks_part_template,
    ).connect()
    model = client.new_part()

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

    if not client.save_as(model, sldprt_path):
        raise RuntimeError(f"SolidWorks SaveAs failed for {sldprt_path}")
    if not sldprt_path.exists() or sldprt_path.stat().st_size < 1:
        raise RuntimeError(f"SLDPRT file not created or empty: {sldprt_path}")

    files_created = [str(sldprt_path)]
    if not client.export_step(model, step_path):
        raise RuntimeError(f"SolidWorks STEP export failed for {step_path}")
    if step_path.exists() and step_path.stat().st_size > 0:
        files_created.append(str(step_path))

    return EngineeringActionResult(
        ok=True,
        software="solidworks",
        action="build_direct_recipe",
        message=f"SolidWorks part built: {sldprt_path}",
        files_created=files_created,
        metrics={"recipe": name, "backend": "solidworks2025"},
    ).model_dump()


def build_solidworks_from_canonical_step(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_step: str | Path,
    out_native: str | Path | None = None,
    inspect: bool = True,
) -> dict:
    """Build gear primitive: CadQuery → canonical STEP → SolidWorks import → SLDPRT.

    Flow:
    1. CadQuery/CQ_Gears generates canonical STEP + metadata
    2. SolidWorks imports STEP via COM
    3. Saves native SLDPRT
    4. Returns EngineeringActionResult with all files and warnings

    NEVER calls SolidWorks gear VBS functions.
    """
    workspace = config.workspace_root
    step_path = ensure_inside_workspace(workspace, out_step)
    ensure_extension(step_path, {".step", ".stp"})
    step_path.parent.mkdir(parents=True, exist_ok=True)

    sldprt_path = ensure_inside_workspace(
        workspace, out_native) if out_native else step_path.with_suffix(".sldprt")

    # Step 1: Build canonical STEP via CadQuery
    cq_result = build_canonical_step_with_cadquery(
        spec=spec, config=config, out_step=str(step_path), inspect=inspect,
    )

    if not step_path.exists() or step_path.stat().st_size < 1:
        return EngineeringActionResult(
            ok=False, software="solidworks",
            action="build_from_canonical_step",
            error="Canonical STEP was not created by CadQuery.",
            files_created=cq_result.get("files_created", []),
            metrics=cq_result.get("metrics", {}),
        ).model_dump()

    # Step 2: SolidWorks imports STEP → saves native SLDPRT
    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient

    client = SolidWorksClient(
        visible=config.solidworks_visible,
        part_template=config.solidworks_part_template,
    ).connect()

    import_ok = client.import_step_as_part(str(step_path), str(sldprt_path))

    if not import_ok:
        return EngineeringActionResult(
            ok=False, software="solidworks",
            action="build_from_canonical_step",
            error="SolidWorks failed to import canonical STEP.",
            files_created=cq_result.get("files_created", []),
            metrics=cq_result.get("metrics", {}),
        ).model_dump()

    files_created = cq_result.get("files_created", []) + [str(sldprt_path)]
    warnings = cq_result.get("warnings", [])
    warnings.append(
        "Native SLDPRT created by importing canonical STEP; "
        "feature tree is not regenerated."
    )

    return EngineeringActionResult(
        ok=True,
        software="solidworks",
        action="build_from_canonical_step",
        message=f"SolidWorks part built from canonical STEP: {sldprt_path}",
        files_created=files_created,
        metrics={
            **cq_result.get("metrics", {}),
            "strategy": "cadquery_step_import",
            "native_path": str(sldprt_path),
        },
        warnings=warnings,
    ).model_dump()


# ── NX ──────────────────────────────────────────────────────────────────────


def build_nx_direct_recipe(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_step: str,
) -> dict:
    """Build simple recipe directly via NX job queue.

    Only supports: box, block_with_hole, l_bracket, stepped_block.
    """
    recipe_feats = [f for f in spec.features if f.type == "recipe"]
    if not recipe_feats:
        return EngineeringActionResult(
            ok=False, software="nx", action="build_direct_recipe",
            error="No recipe features found for NX direct build.",
        ).model_dump()

    recipe_feat = recipe_feats[0]
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
            ok=False, software="nx", action="build_direct_recipe",
            error=(
                f"Recipe '{name}' is not supported for NX direct build. "
                f"Available: {sorted(action_map.keys())}. "
                f"For gears, use primitive 'involute_spur_gear'."
            ),
        ).model_dump()

    from seekflow_engineering_tools.recipes.registry import normalize_recipe_parameters
    from seekflow_engineering_tools.nx.job_queue import NXJobQueue

    params = normalize_recipe_parameters(name, recipe_feat.parameters)
    workspace = config.workspace_root

    step_path = ensure_inside_workspace(workspace, out_step)
    ensure_extension(step_path, {".step", ".stp"})
    step_path.parent.mkdir(parents=True, exist_ok=True)

    prt_path = step_path.with_suffix(".prt")
    ensure_extension(prt_path, {".prt"})

    job_root = config.nx_job_root or (workspace / "nx_jobs")

    nx_params: dict = {"out_prt": str(prt_path), "out_step": str(step_path)}
    if name == "box":
        nx_params.update({"length_mm": params["length_mm"], "width_mm": params["width_mm"],
                          "height_mm": params["height_mm"]})
    elif name == "block_with_hole":
        nx_params.update({"length_mm": params["length_mm"], "width_mm": params["width_mm"],
                          "height_mm": params["height_mm"], "hole_dia_mm": params["hole_dia_mm"]})
    elif name == "l_bracket":
        nx_params.update({"base_length": params["base_length_mm"], "base_width": params["base_width_mm"],
                          "thickness": params["thickness_mm"], "leg_height": params["leg_height_mm"]})
    elif name == "stepped_block":
        nx_params.update({"base_length": params["base_length_mm"], "base_width": params["base_width_mm"],
                          "base_height": params["base_height_mm"], "top_length": params["top_length_mm"],
                          "top_width": params["top_width_mm"], "top_height": params["top_height_mm"]})

    q = NXJobQueue(job_root)
    job_id = q.submit(action, nx_params)
    try:
        result = q.wait(job_id, timeout_s=config.nx_default_timeout_s)
    except TimeoutError:
        return EngineeringActionResult(
            ok=False, software="nx", action="build_direct_recipe",
            error=f"NX job {job_id} timed out after {config.nx_default_timeout_s}s.",
        ).model_dump()

    return EngineeringActionResult(
        ok=bool(result.get("ok")),
        software="nx", action="build_direct_recipe",
        message=result.get("message", ""),
        files_created=result.get("files_created", []),
        metrics={**result.get("metrics", {}), "backend": "nx12", "recipe": name},
        error=result.get("error"),
    ).model_dump()


def build_nx_from_canonical_step(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_step: str | Path,
    out_native: str | Path | None = None,
    inspect: bool = True,
) -> dict:
    """Build gear primitive: CadQuery → canonical STEP → NX import → PRT.

    Flow:
    1. CadQuery/CQ_Gears generates canonical STEP + metadata
    2. NX job queue: import_step_as_prt
    3. Returns EngineeringActionResult with all files and warnings

    NEVER generates involute curves in NXOpen.
    """
    workspace = config.workspace_root
    step_path = ensure_inside_workspace(workspace, out_step)
    ensure_extension(step_path, {".step", ".stp"})
    step_path.parent.mkdir(parents=True, exist_ok=True)

    prt_path = ensure_inside_workspace(
        workspace, out_native) if out_native else step_path.with_suffix(".prt")

    # Step 1: Build canonical STEP via CadQuery
    cq_result = build_canonical_step_with_cadquery(
        spec=spec, config=config, out_step=str(step_path), inspect=inspect,
    )

    if not step_path.exists() or step_path.stat().st_size < 1:
        return EngineeringActionResult(
            ok=False, software="nx",
            action="build_from_canonical_step",
            error="Canonical STEP was not created by CadQuery.",
            files_created=cq_result.get("files_created", []),
            metrics=cq_result.get("metrics", {}),
        ).model_dump()

    # Step 2: NX imports STEP via job queue
    from seekflow_engineering_tools.nx.job_queue import NXJobQueue

    job_root = config.nx_job_root or (workspace / "nx_jobs")
    q = NXJobQueue(job_root)
    job_id = q.submit("import_step_as_prt", {
        "input_step": str(step_path),
        "out_prt": str(prt_path),
        "out_step": str(step_path),
    })

    try:
        result = q.wait(job_id, timeout_s=config.nx_default_timeout_s)
    except TimeoutError:
        return EngineeringActionResult(
            ok=False, software="nx",
            action="build_from_canonical_step",
            error=f"NX import_step_as_prt job {job_id} timed out.",
            files_created=cq_result.get("files_created", []),
        ).model_dump()

    if not bool(result.get("ok")):
        return EngineeringActionResult(
            ok=False, software="nx",
            action="build_from_canonical_step",
            error=result.get("error", "NX import_step_as_prt failed."),
            files_created=cq_result.get("files_created", []),
        ).model_dump()

    files_created = cq_result.get("files_created", []) + result.get("files_created", [])
    warnings = cq_result.get("warnings", [])
    warnings.append(
        "Native PRT created by importing canonical STEP; "
        "NX feature tree is not regenerated."
    )

    return EngineeringActionResult(
        ok=True,
        software="nx",
        action="build_from_canonical_step",
        message=f"NX part built from canonical STEP: {prt_path}",
        files_created=files_created,
        metrics={
            **cq_result.get("metrics", {}),
            "strategy": "cadquery_step_import",
            "native_path": str(prt_path),
        },
        warnings=warnings,
    ).model_dump()
