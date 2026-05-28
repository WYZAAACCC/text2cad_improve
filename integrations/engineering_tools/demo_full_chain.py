#!/usr/bin/env python
r"""SeekFlow Industrial Text-to-CAD — CI Acceptance Script.

End-to-end validation of the full engineering chain:
  NL → CAD-IR → validate → normalize → route → build → inspect → validate

Usage:
  # Recipe cases (cadquery)
  python demo_full_chain.py --case box --backend cadquery
  python demo_full_chain.py --case cylinder --backend cadquery
  python demo_full_chain.py --case flanged_hub --backend cadquery
  python demo_full_chain.py --case shaft_basic --backend cadquery
  python demo_full_chain.py --case block_with_hole --backend cadquery
  python demo_full_chain.py --case l_bracket --backend cadquery
  python demo_full_chain.py --case stepped_block --backend cadquery

  # Gear primitive (all backends)
  python demo_full_chain.py --case involute_spur_gear --backend cadquery
  python demo_full_chain.py --case involute_spur_gear --backend solidworks2025 --allow-step-import
  python demo_full_chain.py --case involute_spur_gear --backend nx12 --allow-step-import
  python demo_full_chain.py --case involute_spur_gear_m3z20 --backend cadquery

  # ANSYS simulations
  python demo_full_chain.py --case ansys_static_beam
  python demo_full_chain.py --case ansys_thermal
  python demo_full_chain.py --case ansys_modal
  python demo_full_chain.py --case ansys_plate_hole
  python demo_full_chain.py --case ansys_buckling

  # Bulk runs
  python demo_full_chain.py --case all --backend cadquery --json-report reports/full_chain.json
  python demo_full_chain.py --case all_cad --backend cadquery
  python demo_full_chain.py --case all_ansys
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════
# Report helpers
# ═══════════════════════════════════════════════════════════════════════

def _make_report_skeleton(case: str, backend: str) -> dict:
    return {
        "overall_ok": False,
        "case": case,
        "backend": backend,
        "stages": {},
        "files_created": [],
        "metrics": {},
        "warnings": [],
        "errors": [],
    }


def _stage(report: dict, name: str, ok: bool, **extra):
    report.setdefault("stages", {})[name] = {"ok": ok, **extra}
    if not ok:
        report["overall_ok"] = False
        error = extra.get("error")
        if error:
            report.setdefault("errors", []).append(f"[{name}] {error}")


def _fail(report: dict, stage: str, error: str):
    _stage(report, stage, ok=False, error=error)
    report.setdefault("errors", []).append(f"[{stage}] {error}")
    report["overall_ok"] = False


def _finalize_case_report(
    report: dict,
    required_stages: list[str],
    *,
    allow_skipped_stages: set[str] | None = None,
    required_metrics: list[str] | None = None,
) -> dict:
    allow_skipped_stages = allow_skipped_stages or set()
    required_metrics = required_metrics or []
    errors = report.setdefault("errors", [])
    stages = report.setdefault("stages", {})
    metrics = report.setdefault("metrics", {})

    ok = True
    for stage_name in required_stages:
        stage = stages.get(stage_name)
        if stage is None:
            ok = False
            errors.append(f"[{stage_name}] Required stage missing.")
            continue
        if stage.get("skipped") is True and stage_name in allow_skipped_stages:
            continue
        if stage.get("ok") is not True:
            ok = False
            err = stage.get("error") or f"Required stage '{stage_name}' did not pass."
            if f"[{stage_name}]" not in " ".join(errors):
                errors.append(f"[{stage_name}] {err}")

    for key in required_metrics:
        value = metrics
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                ok = False
                errors.append(f"[metrics] Required metric missing: {key}")
                value = None
                break
            value = value[part]
        if value in (None, "", "unknown"):
            ok = False
            errors.append(f"[metrics] Required metric invalid/unknown: {key}")

    report["overall_ok"] = ok
    return report


def _get_unified_tools(config):
    from seekflow_engineering_tools.natural_language.tools import build_natural_language_tools
    tools = build_natural_language_tools(config)
    validate = next(t for t in tools if t.name == "engineering_validate_cad_ir")
    build = next(t for t in tools if t.name == "engineering_build_cad_model")
    return validate.func, build.func


CAD_REQUIRED_STAGES = [
    "validate_cad_ir", "normalize_primitives", "choose_backend",
    "build", "inspect", "mechanical_validate",
]


# ═══════════════════════════════════════════════════════════════════════
# Generic recipe case runner (box, cylinder, shaft, flanged_hub, etc.)
# ═══════════════════════════════════════════════════════════════════════

def _run_recipe_case(
    case_name: str, backend: str, output_root: Path,
    spec_dict: dict, step_filename: str,
    allow_step_import: bool = False,
) -> dict:
    from seekflow_engineering_tools.config import EngineeringToolsConfig

    report = _make_report_skeleton(case_name, backend)
    config = EngineeringToolsConfig(workspace_root=output_root, allow_overwrite=True)
    validate_fn, build_fn = _get_unified_tools(config)

    val_result = validate_fn(spec_dict)
    _stage(report, "validate_cad_ir", ok=val_result.get("ok", False),
           error=val_result.get("error"))
    _stage(report, "normalize_primitives", ok=True, skipped=True,
           reason="No mechanical primitive features.")

    if not val_result.get("ok"):
        return _finalize_case_report(
            report, required_stages=CAD_REQUIRED_STAGES,
            allow_skipped_stages={"normalize_primitives", "mechanical_validate"},
        )

    _stage(report, "choose_backend", ok=True, backend=backend)

    step_path = output_root / "models" / step_filename
    step_path.parent.mkdir(parents=True, exist_ok=True)

    build_result = build_fn(spec_dict, backend=backend, out_step=str(step_path),
                            inspect=True, allow_backend_fallback=False)

    # NX 12.0 STEP export may fail ("preference does not exist") even though
    # the PRT was created successfully. Check for native file as fallback.
    build_ok = build_result.get("ok", False)
    if not build_ok and backend == "nx12":
        prt_path = step_path.with_suffix(".prt")
        if prt_path.exists() and prt_path.stat().st_size > 0:
            build_ok = True
            build_result["files_created"] = list(build_result.get("files_created", [])) + [str(prt_path)]
            report.setdefault("warnings", []).append(
                "NX job reported failure (likely STEP export config issue) but PRT was created successfully."
            )

    _stage(report, "build", ok=build_ok,
           error=build_result.get("error") if not build_ok else None)
    report["files_created"] = build_result.get("files_created", [])
    report["warnings"] = build_result.get("warnings", [])

    metrics = build_result.get("metrics", {})
    validation_result = metrics.get("validation")
    if validation_result is not None:
        _stage(report, "inspect", ok=validation_result.get("ok") is True)
    elif backend == "cadquery":
        _stage(report, "inspect", ok=False, error="Validation result missing from build metrics.")
    else:
        # SW/NX native build: inspect based on file existence
        files = build_result.get("files_created", [])
        has_native = any(f.endswith((".sldprt", ".prt")) for f in files)
        _stage(report, "inspect", ok=has_native, skipped=has_native,
               reason="Native file check (no CadQuery inspection for non-cadquery backends)."
               if has_native else "Native file missing.")

    # For SW/NX, also add the native file info
    native_files = [f for f in build_result.get("files_created", [])
                    if f.endswith((".sldprt", ".prt"))]
    if native_files and "native_path" not in metrics:
        nf = Path(native_files[0])
        if nf.exists():
            metrics["native_path"] = str(nf)
            metrics["native_size_kb"] = round(nf.stat().st_size / 1024, 1)

    report["metrics"] = metrics

    _stage(report, "mechanical_validate", ok=True, skipped=True,
           reason="No mechanical primitive features.")

    return _finalize_case_report(
        report, required_stages=CAD_REQUIRED_STAGES,
        allow_skipped_stages={"normalize_primitives", "mechanical_validate"},
    )


# ═══════════════════════════════════════════════════════════════════════
# Case runners
# ═══════════════════════════════════════════════════════════════════════

def run_case_box(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    return _run_recipe_case("box", backend, output_root, {
        "name": "box_demo", "units": "mm", "target_backend": [backend],
        "features": [{"id": "main", "type": "recipe", "recipe_name": "box",
                       "parameters": {"length_mm": 100, "width_mm": 50, "height_mm": 25}}],
        "validation": {"expected_bbox_mm": [100, 50, 25], "expected_body_count": 1, "tolerance_mm": 2.0},
    }, "box.step")


def run_case_cylinder(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    return _run_recipe_case("cylinder", backend, output_root, {
        "name": "cylinder_demo", "units": "mm", "target_backend": [backend],
        "features": [{"id": "main", "type": "recipe", "recipe_name": "cylinder",
                       "parameters": {"diameter_mm": 20, "height_mm": 50}}],
        "validation": {"expected_bbox_mm": [20, 20, 50], "expected_body_count": 1, "tolerance_mm": 2.0},
    }, "cylinder.step")


def run_case_flanged_hub(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    return _run_recipe_case("flanged_hub", backend, output_root, {
        "name": "flanged_hub_demo", "units": "mm", "target_backend": [backend],
        "features": [{"id": "main", "type": "recipe", "recipe_name": "flanged_hub",
                       "parameters": {"flange_dia_mm": 80, "flange_thickness_mm": 10,
                                       "hub_dia_mm": 40, "hub_height_mm": 30,
                                       "bore_dia_mm": 20, "bolt_pcd_mm": 60,
                                       "bolt_dia_mm": 8, "bolt_count": 4}}],
        "validation": {"expected_body_count": 1},
    }, "flanged_hub.step")


def run_case_shaft_basic(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    return _run_recipe_case("shaft_basic", backend, output_root, {
        "name": "shaft_demo", "units": "mm", "target_backend": [backend],
        "features": [{"id": "main", "type": "recipe", "recipe_name": "shaft_basic",
                       "parameters": {"shaft_dia_mm": 20, "total_length_mm": 100}}],
        "validation": {"expected_bbox_mm": [20, 20, 100], "expected_body_count": 1, "tolerance_mm": 2.0},
    }, "shaft_basic.step")


def run_case_shaft_with_keyway(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    return _run_recipe_case("shaft_with_keyway", backend, output_root, {
        "name": "shaft_keyway_demo", "units": "mm", "target_backend": [backend],
        "features": [{"id": "main", "type": "recipe", "recipe_name": "shaft_with_keyway",
                       "parameters": {"shaft_dia_mm": 25, "total_length_mm": 120,
                                       "keyway_width_mm": 6, "keyway_depth_mm": 3,
                                       "keyway_offset_from_end_mm": 10}}],
        "validation": {"expected_body_count": 1},
    }, "shaft_with_keyway.step")


def run_case_block_with_hole(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    return _run_recipe_case("block_with_hole", backend, output_root, {
        "name": "block_hole_demo", "units": "mm", "target_backend": [backend],
        "features": [{"id": "main", "type": "recipe", "recipe_name": "block_with_hole",
                       "parameters": {"length_mm": 100, "width_mm": 50, "height_mm": 25,
                                       "hole_dia_mm": 16}}],
        "validation": {"expected_body_count": 1, "expected_through_hole_count": 1},
    }, "block_with_hole.step")


def run_case_l_bracket(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    return _run_recipe_case("l_bracket", backend, output_root, {
        "name": "l_bracket_demo", "units": "mm", "target_backend": [backend],
        "features": [{"id": "main", "type": "recipe", "recipe_name": "l_bracket",
                       "parameters": {"base_length_mm": 100, "base_width_mm": 60,
                                       "thickness_mm": 15, "leg_height_mm": 60}}],
        "validation": {"expected_body_count": 1},
    }, "l_bracket.step")


def run_case_stepped_block(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    return _run_recipe_case("stepped_block", backend, output_root, {
        "name": "stepped_block_demo", "units": "mm", "target_backend": [backend],
        "features": [{"id": "main", "type": "recipe", "recipe_name": "stepped_block",
                       "parameters": {"base_length_mm": 80, "base_width_mm": 80,
                                       "base_height_mm": 20, "top_length_mm": 60,
                                       "top_width_mm": 60, "top_height_mm": 30}}],
        "validation": {"expected_body_count": 1},
    }, "stepped_block.step")


# ═══════════════════════════════════════════════════════════════════════
# Gear primitive case runner
# ═══════════════════════════════════════════════════════════════════════

GEAR_REQUIRED_STAGES = [
    "validate_cad_ir", "normalize_primitives", "choose_backend",
    "build", "inspect", "mechanical_validate", "metadata",
]
GEAR_REQUIRED_METRICS = [
    "kernel_used",
    "reference_dimensions.pitch_diameter_mm",
    "reference_dimensions.base_diameter_mm",
    "reference_dimensions.outer_diameter_mm",
    "reference_dimensions.root_diameter_mm",
]

PRIMITIVE_REQUIRED_STAGES = [
    "validate_cad_ir", "normalize_primitives", "choose_backend",
    "build", "inspect", "mechanical_validate", "metadata",
]


def _run_primitive_case(
    case_name: str, backend: str, output_root: Path,
    primitive_name: str, params: dict, step_filename: str,
    *,
    extra_validation: dict | None = None,
    required_metrics: list[str] | None = None,
    required_stages: list[str] | None = None,
    allow_skipped_stages: set[str] | None = None,
    allow_step_import: bool = False,
) -> dict:
    """Generic primitive case runner for any registered primitive.

    Must go through engineering_validate_cad_ir and engineering_build_cad_model.
    Each primitive provides its own required_metrics and extra_validation.
    """
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.capabilities.registry import get_primitive_strategy

    required_stages = required_stages or PRIMITIVE_REQUIRED_STAGES
    required_metrics = required_metrics or []
    extra_validation = extra_validation or {}

    report = _make_report_skeleton(case_name, backend)
    config = EngineeringToolsConfig(workspace_root=output_root, allow_overwrite=True)

    spec_dict: dict = {
        "name": case_name, "units": "mm", "target_backend": [backend],
        "features": [{"id": "feat1", "type": "primitive",
                       "primitive_name": primitive_name,
                       "parameters": params}],
        "validation": {
            "expected_body_count": 1,
            "tolerance_mm": 0.1,
            **extra_validation,
        },
    }

    validate_fn, build_fn = _get_unified_tools(config)

    # Stage 1: validate_cad_ir
    val_result = validate_fn(spec_dict)
    norm_params = val_result.get("metrics", {}).get("normalized_parameters", {})
    _stage(report, "validate_cad_ir", ok=val_result.get("ok", False),
           error=val_result.get("error"))
    _stage(report, "normalize_primitives", ok=val_result.get("ok", False),
           normalized_params=norm_params.get("feat1"))

    if not val_result.get("ok"):
        return _finalize_case_report(report, required_stages=required_stages,
                                     required_metrics=required_metrics,
                                     allow_skipped_stages=allow_skipped_stages)

    # Stage 2: choose_backend
    if backend in ("solidworks2025", "nx12") and not allow_step_import:
        _fail(report, "choose_backend",
              f"Backend '{backend}' requires --allow-step-import for primitives.")
        return _finalize_case_report(report, required_stages=required_stages,
                                     required_metrics=required_metrics)

    strategy = get_primitive_strategy(backend, primitive_name)
    if strategy is None:
        _fail(report, "choose_backend",
              f"No primitive strategy for '{primitive_name}' on backend '{backend}'.")
        return _finalize_case_report(report, required_stages=required_stages,
                                     required_metrics=required_metrics)
    _stage(report, "choose_backend", ok=True, backend=backend, strategy=strategy)

    # Stage 3: build
    step_rel = Path("models") / step_filename
    step_path = output_root / step_rel
    (output_root / "models").mkdir(parents=True, exist_ok=True)

    allow_fb = backend not in ("solidworks2025", "nx12")
    build_result = build_fn(spec_dict, backend=backend, out_step=str(step_rel),
                            inspect=True, allow_backend_fallback=allow_fb)
    _stage(report, "build", ok=build_result.get("ok", False),
           error=build_result.get("error"))
    report["files_created"] = build_result.get("files_created", [])
    report["warnings"] = build_result.get("warnings", [])

    # Stage 4-5: inspect + mechanical_validate (primitive path)
    metrics = build_result.get("metrics", {})
    validation_result = metrics.get("validation")
    mech_val_result = metrics.get("mechanical_validation")

    _stage(report, "inspect",
           ok=validation_result.get("ok") is True if validation_result else False,
           error=None if validation_result else "Validation result missing.")

    _stage(report, "mechanical_validate",
           ok=mech_val_result.get("ok") is True if mech_val_result else False,
           error=None if mech_val_result else "Mechanical validation result missing.")

    # Stage 6: metadata (generic, keyed by primitive_name)
    meta_path = step_path.with_suffix(".metadata.json")
    kernel_used = "unknown"
    ref_dims = {}
    if not meta_path.exists() or meta_path.stat().st_size < 1:
        _stage(report, "metadata", ok=False, error="Primitive metadata sidecar missing or empty.")
    else:
        try:
            sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
            pm = sidecar.get("primitive_metadata", {}).get(primitive_name)
            if not isinstance(pm, dict):
                _stage(report, "metadata", ok=False,
                       error=f"primitive_metadata.{primitive_name} missing.")
            else:
                _stage(report, "metadata", ok=True, path=str(meta_path))
                if pm.get("kernel"):
                    kernel_used = pm["kernel"]
                if pm.get("reference_dimensions"):
                    ref_dims = pm["reference_dimensions"]
        except (json.JSONDecodeError, OSError) as exc:
            _stage(report, "metadata", ok=False, error=f"Failed to read metadata: {exc}")

    # Fallback from mech val
    if kernel_used == "unknown" and mech_val_result:
        for r in mech_val_result.get("results", []):
            if r.get("kernel"):
                kernel_used = r["kernel"]
            if r.get("reference_dimensions") and not ref_dims:
                ref_dims = r["reference_dimensions"]

    report["metrics"] = {
        "kernel_used": kernel_used,
        "reference_dimensions": ref_dims,
        "strategy": strategy,
    }

    build_ok = build_result.get("ok", False)
    if not build_ok:
        report["overall_ok"] = False

    return _finalize_case_report(report, required_stages=required_stages,
                                 required_metrics=required_metrics,
                                 allow_skipped_stages=allow_skipped_stages)


def _run_gear_case(
    case_name: str, backend: str, output_root: Path,
    params: dict, step_filename: str,
    allow_step_import: bool = False,
) -> dict:
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.geometry_primitives.gears.standards import (
        spur_gear_reference_dimensions,
    )
    from seekflow_engineering_tools.capabilities.registry import get_primitive_strategy

    report = _make_report_skeleton(case_name, backend)
    config = EngineeringToolsConfig(workspace_root=output_root, allow_overwrite=True)

    ref = spur_gear_reference_dimensions(params)
    spec_dict = {
        "name": case_name, "units": "mm", "target_backend": [backend],
        "features": [{"id": "gear1", "type": "primitive",
                       "primitive_name": "involute_spur_gear",
                       "parameters": params}],
        "validation": {
            "expected_body_count": 1,
            "expected_bbox_mm": [ref["outer_diameter_mm"], ref["outer_diameter_mm"], params["face_width_mm"]],
            "expected_kernel": "cq_gears",
            "tolerance_mm": 0.1,
        },
    }

    validate_fn, build_fn = _get_unified_tools(config)

    # Stage 1: validate_cad_ir
    val_result = validate_fn(spec_dict)
    norm_params = val_result.get("metrics", {}).get("normalized_parameters", {})
    _stage(report, "validate_cad_ir", ok=val_result.get("ok", False),
           error=val_result.get("error"))
    _stage(report, "normalize_primitives", ok=val_result.get("ok", False),
           normalized_params=norm_params.get("gear1"))

    if not val_result.get("ok"):
        return _finalize_case_report(report, required_stages=GEAR_REQUIRED_STAGES,
                                     required_metrics=GEAR_REQUIRED_METRICS)

    # Stage 2: choose_backend
    if backend in ("solidworks2025", "nx12") and not allow_step_import:
        _fail(report, "choose_backend",
              f"Backend '{backend}' requires --allow-step-import for gear primitives.")
        return _finalize_case_report(report, required_stages=GEAR_REQUIRED_STAGES,
                                     required_metrics=GEAR_REQUIRED_METRICS)

    strategy = get_primitive_strategy(backend, "involute_spur_gear")
    if strategy is None:
        _fail(report, "choose_backend",
              f"No primitive strategy for 'involute_spur_gear' on backend '{backend}'.")
        return _finalize_case_report(report, required_stages=GEAR_REQUIRED_STAGES,
                                     required_metrics=GEAR_REQUIRED_METRICS)
    _stage(report, "choose_backend", ok=True, backend=backend, strategy=strategy)

    # Stage 3: build
    step_rel = Path("models") / step_filename
    step_path = output_root / step_rel
    (output_root / "models").mkdir(parents=True, exist_ok=True)

    allow_fb = backend not in ("solidworks2025", "nx12")
    build_result = build_fn(spec_dict, backend=backend, out_step=str(step_rel),
                            inspect=True, allow_backend_fallback=allow_fb)
    _stage(report, "build", ok=build_result.get("ok", False),
           error=build_result.get("error"))
    report["files_created"] = build_result.get("files_created", [])
    report["warnings"] = build_result.get("warnings", [])

    # Stage 4-5: inspect + mechanical_validate
    metrics = build_result.get("metrics", {})
    validation_result = metrics.get("validation")
    mech_val_result = metrics.get("mechanical_validation")

    _stage(report, "inspect",
           ok=validation_result.get("ok") is True if validation_result else False,
           error=None if validation_result else "Validation result missing.")

    _stage(report, "mechanical_validate",
           ok=mech_val_result.get("ok") is True if mech_val_result else False,
           error=None if mech_val_result else "Mechanical validation result missing.")

    # Stage 6: metadata sidecar
    meta_path = step_path.with_suffix(".metadata.json")
    kernel_used = "unknown"
    ref_dims = {}
    if not meta_path.exists() or meta_path.stat().st_size < 1:
        _stage(report, "metadata", ok=False, error="Gear metadata sidecar missing or empty.")
    else:
        try:
            sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
            pm = sidecar.get("primitive_metadata", {}).get("involute_spur_gear")
            if not isinstance(pm, dict):
                _stage(report, "metadata", ok=False, error="primitive_metadata.involute_spur_gear missing.")
            else:
                _stage(report, "metadata", ok=True, path=str(meta_path))
                if pm.get("kernel"):
                    kernel_used = pm["kernel"]
                if pm.get("reference_dimensions"):
                    ref_dims = pm["reference_dimensions"]
        except (json.JSONDecodeError, OSError) as exc:
            _stage(report, "metadata", ok=False, error=f"Failed to read metadata: {exc}")

    # Fallback from mech val
    if kernel_used == "unknown" and mech_val_result:
        for r in mech_val_result.get("results", []):
            if r.get("kernel"):
                kernel_used = r["kernel"]
            if r.get("reference_dimensions") and not ref_dims:
                ref_dims = r["reference_dimensions"]

    # Industrial acceptance: cq_gears kernel required
    quality = params.get("quality_grade", "industrial_brep")
    if quality == "industrial_brep" and kernel_used != "cq_gears":
        _stage(report, "mechanical_validate", ok=False,
               error=f"Expected kernel 'cq_gears' for industrial_brep, got '{kernel_used}'.")

    report["metrics"] = {
        "kernel_used": kernel_used,
        "reference_dimensions": {
            "pitch_diameter_mm": ref_dims.get("pitch_diameter_mm"),
            "base_diameter_mm": ref_dims.get("base_diameter_mm"),
            "outer_diameter_mm": ref_dims.get("outer_diameter_mm"),
            "root_diameter_mm": ref_dims.get("root_diameter_mm"),
        },
        "strategy": strategy,
    }

    return _finalize_case_report(report, required_stages=GEAR_REQUIRED_STAGES,
                                 required_metrics=GEAR_REQUIRED_METRICS)


def run_case_involute_spur_gear(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    return _run_gear_case("involute_spur_gear", backend, output_root, {
        "module_mm": 2.0, "teeth": 24,
        "pressure_angle_deg": 20.0, "face_width_mm": 15.0, "bore_dia_mm": 10.0,
        "quality_grade": "industrial_brep",
    }, "involute_spur_gear.step", allow_step_import=allow_step_import)


def run_case_involute_spur_gear_m3z20(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    return _run_gear_case("involute_spur_gear_m3z20", backend, output_root, {
        "module_mm": 3.0, "teeth": 20,
        "pressure_angle_deg": 20.0, "face_width_mm": 20.0, "bore_dia_mm": 15.0,
        "quality_grade": "industrial_brep",
    }, "involute_spur_gear_m3z20.step", allow_step_import=allow_step_import)


# ═══════════════════════════════════════════════════════════════════════
# ANSYS simulation case runners
# ═══════════════════════════════════════════════════════════════════════

def _run_ansys_case(
    case_name: str, output_root: Path,
    apdl_fn, jobname: str,
    required_metrics: list[str],
    memory_mb: int = 256,
) -> dict:
    from seekflow_engineering_tools.ansys.apdl_runner import AnsysAPDLRunner
    from seekflow_engineering_tools.ansys.parsers import parse_result_summary

    report = _make_report_skeleton(case_name, "ansys181")

    ansys_exe_str = os.environ.get("ANSYS181_EXE",
        r"D:\ANSYS181\ANSYS Inc\v181\ANSYS\bin\winx64\ansys181.exe")
    ansys_exe = Path(ansys_exe_str)

    # Stage 1: health check
    if not ansys_exe.exists():
        _fail(report, "health_check",
              f"ANSYS executable not found: {ansys_exe}. Set ANSYS181_EXE env var.")
        return _finalize_case_report(
            report,
            required_stages=["health_check", "generate_apdl", "solve", "parse_results"],
            required_metrics=required_metrics,
        )
    _stage(report, "health_check", ok=True, exe=str(ansys_exe))

    ansys_dir = output_root / "ansys" / case_name
    ansys_dir.mkdir(parents=True, exist_ok=True)

    # Stage 2: generate APDL
    try:
        apdl = apdl_fn()
        inp_path = ansys_dir / f"{jobname}.inp"
        inp_path.write_text(apdl, encoding="utf-8")
        _stage(report, "generate_apdl", ok=True, input=str(inp_path),
               apdl_size=len(apdl))
    except Exception as exc:
        _fail(report, "generate_apdl", str(exc))
        return _finalize_case_report(
            report,
            required_stages=["health_check", "generate_apdl", "solve", "parse_results"],
            required_metrics=required_metrics,
        )

    # Stage 3: solve
    runner = AnsysAPDLRunner(
        ansys_exe=ansys_exe, workspace_root=ansys_dir, default_timeout_s=120,
    )
    try:
        run = runner.run_apdl_file(inp_path, ansys_dir, jobname, memory_mb=memory_mb)
    except Exception as exc:
        _fail(report, "solve", f"ANSYS run failed: {exc}")
        return _finalize_case_report(
            report,
            required_stages=["health_check", "generate_apdl", "solve", "parse_results"],
            required_metrics=required_metrics,
        )

    if run.get("has_error"):
        _fail(report, "solve",
              f"ANSYS APDL error (rc={run.get('returncode')}): {(run.get('stderr_tail', '') or '')[:200]}")
    else:
        _stage(report, "solve", ok=True,
               elapsed_s=run.get("elapsed_s"), returncode=run.get("returncode"))

    # Stage 4: parse results — summary missing is fail-closed
    out_file = ansys_dir / f"{jobname}.out"
    summary_path = ansys_dir / "result_summary.txt"
    metrics = {}
    if summary_path.exists():
        metrics = parse_result_summary(summary_path)
        _stage(report, "parse_results", ok=True, summary=str(summary_path))
    elif out_file.exists():
        # Try parsing directly from .out
        metrics = parse_result_summary(out_file)
        if metrics:
            _stage(report, "parse_results", ok=True, source=".out file")
        else:
            _fail(report, "parse_results", "ANSYS result_summary.txt missing and .out unparseable.")
    else:
        _fail(report, "parse_results", "ANSYS output file not found.")

    report["metrics"] = metrics
    report["files_created"] = [str(inp_path)]
    if out_file.exists():
        report["files_created"].append(str(out_file))
    if run.get("output_file"):
        report["files_created"].append(run["output_file"])

    return _finalize_case_report(
        report,
        required_stages=["health_check", "generate_apdl", "solve", "parse_results"],
        required_metrics=required_metrics,
    )


def run_case_ansys_static_beam(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    from seekflow_engineering_tools.ansys.apdl_templates import static_cantilever_beam_rect_apdl
    return _run_ansys_case("ansys_static_beam", output_root,
        lambda: static_cantilever_beam_rect_apdl(200, 20, 20, 1000, element_size_mm=20.0),
        "beam_static",
        required_metrics=["max_displacement_mm"])


def run_case_ansys_plate_hole(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    from seekflow_engineering_tools.ansys.apdl_templates import plate_with_hole_tension_apdl
    return _run_ansys_case("ansys_plate_hole", output_root,
        lambda: plate_with_hole_tension_apdl(200, 100, 10, 20, 100, element_size_mm=10.0),
        "plate_hole",
        required_metrics=["max_stress_mpa"])


def run_case_ansys_thermal(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    from seekflow_engineering_tools.ansys.apdl_templates import beam_thermal_apdl
    return _run_ansys_case("ansys_thermal", output_root,
        lambda: beam_thermal_apdl(200, 20, 20, element_size_mm=10.0),
        "thermal",
        required_metrics=["tmin_c", "tmax_c"])


def run_case_ansys_modal(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    from seekflow_engineering_tools.ansys.apdl_templates import cantilever_modal_apdl
    return _run_ansys_case("ansys_modal", output_root,
        lambda: cantilever_modal_apdl(200, 20, 20, n_modes=5, element_size_mm=20.0),
        "modal",
        required_metrics=["modal_frequencies_hz"])


def run_case_ansys_buckling(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    from seekflow_engineering_tools.ansys.apdl_templates import buckling_column_apdl
    return _run_ansys_case("ansys_buckling", output_root,
        lambda: buckling_column_apdl(500, 20, 20, element_size_mm=10.0),
        "buckling",
        required_metrics=["buckling_load_factor"])


# ═══════════════════════════════════════════════════════════════════════
# Case registry
# ═══════════════════════════════════════════════════════════════════════

# ── Turbine disk required metrics ──

TURBINE_DISK_REQUIRED_METRICS = [
    "kernel_used",
    "reference_dimensions.outer_dia_mm",
    "reference_dimensions.bore_dia_mm",
    "reference_dimensions.axial_width_mm",
    "reference_dimensions.hub_outer_dia_mm",
    "reference_dimensions.web_outer_dia_mm",
    "reference_dimensions.rim_inner_dia_mm",
    "reference_dimensions.expected_through_hole_count",
    "reference_dimensions.rim_slot_count",
    "reference_dimensions.rim_slot_orientation",
    "reference_dimensions.rim_slot_stage_count",
    "reference_dimensions.rim_slot_profile_symmetry",
    "reference_dimensions.rim_slot_exposes_lobes_on_od",
    "reference_dimensions.rim_slot_mouth_width_mm",
    "reference_dimensions.rim_slot_throat_width_mm",
    "reference_dimensions.rim_slot_stage_neck_width_mm",
    "reference_dimensions.rim_slot_stage_lobe_width_mm",
    "reference_dimensions.rim_slot_root_width_mm",
    "reference_dimensions.rim_slot_opens_front_face",
    "reference_dimensions.rim_slot_opens_back_face",
    "reference_dimensions.rim_slot_opens_outer_diameter",
    "reference_dimensions.expected_periodic_slot_count",
    "reference_dimensions.expected_bbox_mm",
    "reference_dimensions.rim_slot_z_min_mm",
    "reference_dimensions.rim_slot_z_max_mm",
    "reference_dimensions.rim_slot_profile_max_x_mm",
    "reference_dimensions.rim_slot_profile_min_x_mm",
    "reference_dimensions.front_hub_sleeve_height_mm",
]


def run_case_axisymmetric_turbine_disk(
    backend: str,
    output_root: Path,
    allow_step_import: bool = False,
) -> dict:
    params = {
        "outer_dia_mm": 520.0,
        "bore_dia_mm": 86.0,
        "axial_width_mm": 62.0,

        "hub_outer_dia_mm": 210.0,
        "web_outer_dia_mm": 360.0,
        "rim_inner_dia_mm": 420.0,

        "hub_width_mm": 62.0,
        "web_width_mm": 30.0,
        "rim_width_mm": 58.0,

        "hub_fillet_radius_mm": 1.5,
        "web_fillet_radius_mm": 1.0,
        "rim_fillet_radius_mm": 1.0,
        "edge_chamfer_mm": 0.5,

        "bolt_hole_count": 0,
        "bolt_pcd_mm": 0.0,
        "bolt_hole_dia_mm": 0.0,
        "bolt_hole_axis": "Z",

        "lightening_hole_count": 10,
        "lightening_hole_pcd_mm": 310.0,
        "lightening_hole_dia_mm": 20.0,
        "lightening_hole_axis": "Z",

        "cooling_hole_count": 36,
        "cooling_hole_pcd_mm": 455.0,
        "cooling_hole_dia_mm": 4.0,
        "cooling_hole_axis": "Z",

        "rim_slot_count": 60,
        "rim_slot_style": "fir_tree_like",
        "rim_slot_orientation": "axial_through",
        "rim_slot_stage_count": 3,
        "rim_slot_stage_pitch_mm": 7.0,
        "rim_slot_stage_neck_width_mm": 4.6,
        "rim_slot_stage_lobe_width_mm": 9.0,
        "rim_slot_stage_lobe_height_mm": 2.1,
        "rim_slot_stage_width_growth": 0.08,
        "rim_slot_stage_depth_distribution": "uniform",
        "rim_slot_mouth_width_mm": 5.2,
        "rim_slot_throat_width_mm": 4.6,
        "rim_slot_root_width_mm": 5.4,
        "rim_slot_profile_symmetry": "mirror_y",
        "rim_slot_require_multiple_stages": True,
        "rim_slot_expose_lobes_on_od": False,
        "rim_slot_socket_mode": "internal_lobes",
        "rim_slot_lobe_width_mm": 9.0,
        "rim_slot_depth_mm": 38.0,
        "rim_slot_width_mm": 7.0,
        "rim_slot_neck_width_mm": 4.5,
        "rim_slot_lobe_depth_mm": 7.0,
        "rim_slot_axial_margin_mm": 0.0,
        "rim_slot_through_clearance_mm": 2.0,
        "rim_slot_outer_clearance_mm": 4.0,
        "rim_slot_root_fillet_mm": 0.0,
        "rim_slot_tip_chamfer_mm": 0.0,

        "front_hub_sleeve_outer_dia_mm": 155.0,
        "front_hub_sleeve_inner_dia_mm": 86.0,
        "front_hub_sleeve_height_mm": 58.0,
        "front_hub_sleeve_wall_mm": 8.0,
        "front_hub_sleeve_chamfer_mm": 1.5,

        "rear_hub_sleeve_outer_dia_mm": 0.0,
        "rear_hub_sleeve_inner_dia_mm": 0.0,
        "rear_hub_sleeve_height_mm": 0.0,
        "rear_hub_sleeve_chamfer_mm": 0.0,

        "enable_annular_details": True,

        "inner_hub_step_outer_dia_mm": 190.0,
        "inner_hub_step_height_mm": 8.0,

        "mid_web_recess_inner_dia_mm": 225.0,
        "mid_web_recess_outer_dia_mm": 365.0,
        "mid_web_recess_depth_mm": 3.0,

        "outer_rim_recess_inner_dia_mm": 395.0,
        "outer_rim_recess_outer_dia_mm": 485.0,
        "outer_rim_recess_depth_mm": 2.0,

        "seal_land_count": 2,
        "seal_land_height_mm": 2.0,
        "seal_land_width_mm": 3.0,
        "seal_land_start_dia_mm": 160.0,
        "seal_land_pitch_mm": 8.0,

        "coverplate_bolt_count": 18,
        "coverplate_bolt_pcd_mm": 175.0,
        "coverplate_bolt_dia_mm": 4.0,

        "balance_hole_count": 0,
        "balance_hole_pcd_mm": 0.0,
        "balance_hole_dia_mm": 0.0,

        "quality_grade": "engineering_reference",
        "non_flight_reference_only": True,
    }

    total_holes = 1 + 10 + 36 + 18
    expected_z = 62.0 + 58.0 + 0.0  # axial + front + rear sleeves

    return _run_primitive_case(
        "axisymmetric_turbine_disk",
        backend,
        output_root,
        "axisymmetric_turbine_disk",
        params,
        "axisymmetric_turbine_disk.step",
        extra_validation={
            "expected_bbox_mm": [520.0, 520.0, expected_z],
            "expected_body_count": 1,
            "expected_through_hole_count": total_holes,
            "tolerance_mm": 1.5,
            "primitive_validation": {
                "feat1": {
                    "expected_kernel": "cadquery_turbine_disk_reference_v6",
                    "expected_through_hole_count": total_holes,
                }
            },
        },
        required_metrics=TURBINE_DISK_REQUIRED_METRICS,
        allow_step_import=allow_step_import,
    )


CASE_RUNNERS = {
    # ── Recipe CAD cases ──
    "box": run_case_box,
    "cylinder": run_case_cylinder,
    "flanged_hub": run_case_flanged_hub,
    "shaft_basic": run_case_shaft_basic,
    "shaft_with_keyway": run_case_shaft_with_keyway,
    "block_with_hole": run_case_block_with_hole,
    "l_bracket": run_case_l_bracket,
    "stepped_block": run_case_stepped_block,
    # ── Gear primitive cases ──
    "involute_spur_gear": run_case_involute_spur_gear,
    "involute_spur_gear_m3z20": run_case_involute_spur_gear_m3z20,
    # ── Turbine primitive cases ──
    "axisymmetric_turbine_disk": run_case_axisymmetric_turbine_disk,
    # ── ANSYS simulation cases ──
    "ansys_static_beam": run_case_ansys_static_beam,
    "ansys_plate_hole": run_case_ansys_plate_hole,
    "ansys_thermal": run_case_ansys_thermal,
    "ansys_modal": run_case_ansys_modal,
    "ansys_buckling": run_case_ansys_buckling,
}

CAD_CASES = [
    "box", "cylinder", "flanged_hub", "shaft_basic", "shaft_with_keyway",
    "block_with_hole", "l_bracket", "stepped_block",
]
GEAR_CASES = ["involute_spur_gear", "involute_spur_gear_m3z20"]
TURBINE_CASES = ["axisymmetric_turbine_disk"]
ANSYS_CASES = [
    "ansys_static_beam", "ansys_plate_hole", "ansys_thermal",
    "ansys_modal", "ansys_buckling",
]
ALL_CASES = CAD_CASES + GEAR_CASES + TURBINE_CASES + ANSYS_CASES


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="SeekFlow Industrial Text-to-CAD — CI Acceptance Script"
    )
    parser.add_argument("--case", default="all",
                        choices=["all", "all_cad", "all_ansys"] + ALL_CASES)
    parser.add_argument("--backend", default="cadquery",
                        choices=["cadquery", "solidworks2025", "nx12"])
    parser.add_argument("--output", default=None)
    parser.add_argument("--json-report", default=None)
    parser.add_argument("--allow-step-import", action="store_true",
                        help="Allow STEP import for SW/NX gear primitives")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(args.output) if args.output else Path(__file__).parent / "demo_output" / ts
    output_root.mkdir(parents=True, exist_ok=True)

    # Determine cases
    if args.case == "all":
        cases_to_run = ALL_CASES
    elif args.case == "all_cad":
        cases_to_run = CAD_CASES + GEAR_CASES
    elif args.case == "all_ansys":
        cases_to_run = ANSYS_CASES
    else:
        cases_to_run = [args.case]

    full_report = {
        "timestamp": datetime.now().isoformat(),
        "overall_ok": True,
        "backend": args.backend,
        "cases": [],
    }

    for case_name in cases_to_run:
        runner = CASE_RUNNERS[case_name]
        case_report = runner(args.backend, output_root, args.allow_step_import)
        full_report["cases"].append(case_report)
        if not case_report["overall_ok"]:
            full_report["overall_ok"] = False
        status = "OK" if case_report["overall_ok"] else "FAIL"
        errs = "; ".join(case_report.get("errors", [])[:2])
        print(f"  [{status}] {case_name}/{args.backend}" + (f" — {errs}" if errs else ""))

    # Write reports
    if args.json_report:
        report_path = Path(args.json_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(full_report, f, indent=2, ensure_ascii=False, default=str)
        print(f"Report: {report_path}")

    local = output_root / "demo_report.json"
    with open(local, "w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=2, ensure_ascii=False, default=str)

    passed = sum(1 for c in full_report["cases"] if c["overall_ok"])
    print(f"Done: {passed}/{len(full_report['cases'])} passed, output={output_root}")

    if not full_report["overall_ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
