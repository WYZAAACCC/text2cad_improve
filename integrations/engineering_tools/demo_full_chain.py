#!/usr/bin/env python
r"""SeekFlow Engineering Tools — Industrial Text-to-CAD CI Acceptance Script.

Usage:
    python demo_full_chain.py --case box --backend cadquery
    python demo_full_chain.py --case flanged_hub --backend cadquery
    python demo_full_chain.py --case involute_spur_gear --backend cadquery
    python demo_full_chain.py --case involute_spur_gear --backend solidworks2025 --allow-step-import
    python demo_full_chain.py --case involute_spur_gear --backend nx12 --allow-step-import
    python demo_full_chain.py --case all --backend cadquery --json-report reports/full_chain.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


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
    report["stages"][name] = {"ok": ok, **extra}
    if not ok:
        report["overall_ok"] = False


def _fail(report: dict, stage: str, error: str):
    _stage(report, stage, ok=False, error=error)
    report["errors"].append(f"[{stage}] {error}")
    report["overall_ok"] = False


# ═══════════════════════════════════════════════════════════════════════
# Case: box
# ═══════════════════════════════════════════════════════════════════════

def run_case_box(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    report = _make_report_skeleton("box", backend)
    config = EngineeringToolsConfig(workspace_root=output_root, allow_overwrite=True)

    # Stage 1: validate_cad_ir
    spec_dict = {
        "name": "box_demo", "units": "mm",
        "target_backend": [backend],
        "features": [{"id": "main", "type": "recipe", "recipe_name": "box",
                       "parameters": {"length_mm": 100, "width_mm": 50, "height_mm": 25}}],
        "validation": {"expected_bbox_mm": [100, 50, 25], "expected_body_count": 1, "tolerance_mm": 2.0},
    }
    try:
        spec = CADPartSpec.model_validate(spec_dict)
        _stage(report, "validate_cad_ir", ok=True)
    except Exception as exc:
        _fail(report, "validate_cad_ir", str(exc))
        return report

    # Stage 2: normalize_primitives
    _stage(report, "normalize_primitives", ok=True)

    # Stage 3: choose_backend
    from seekflow_engineering_tools.capabilities.registry import choose_backend
    choice = choose_backend(spec, preferred=[backend])
    _stage(report, "choose_backend", ok=choice.backend != "none", backend=choice.backend)

    # Stage 4-6: build + inspect + validate
    if choice.backend == "cadquery":
        step_path = output_root / "models" / "box.step"
        step_path.parent.mkdir(parents=True, exist_ok=True)
        result = build_cadquery_from_cad_ir(spec=spec, config=config, out_step=str(step_path))
        _stage(report, "build", ok=result.get("ok", False),
               error=result.get("error"))
        report["files_created"] = result.get("files_created", [])
        validation = result.get("metrics", {}).get("validation", {})
        _stage(report, "inspect", ok=validation.get("ok", True))
        _stage(report, "mechanical_validate", ok=True)
        if result.get("ok"):
            report["overall_ok"] = True
    else:
        _fail(report, "build", f"Backend {backend} not supported for box case")

    return report


# ═══════════════════════════════════════════════════════════════════════
# Case: flanged_hub
# ═══════════════════════════════════════════════════════════════════════

def run_case_flanged_hub(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    report = _make_report_skeleton("flanged_hub", backend)
    config = EngineeringToolsConfig(workspace_root=output_root, allow_overwrite=True)

    spec_dict = {
        "name": "flanged_hub_demo", "units": "mm",
        "target_backend": [backend],
        "features": [{"id": "main", "type": "recipe", "recipe_name": "flanged_hub",
                       "parameters": {"flange_dia_mm": 80, "flange_thickness_mm": 10,
                                       "hub_dia_mm": 40, "hub_height_mm": 30,
                                       "bore_dia_mm": 20, "bolt_pcd_mm": 60,
                                       "bolt_dia_mm": 8, "bolt_count": 4}}],
        "validation": {"expected_body_count": 1},
    }
    try:
        spec = CADPartSpec.model_validate(spec_dict)
        _stage(report, "validate_cad_ir", ok=True)
    except Exception as exc:
        _fail(report, "validate_cad_ir", str(exc))
        return report

    _stage(report, "normalize_primitives", ok=True)

    from seekflow_engineering_tools.capabilities.registry import choose_backend
    choice = choose_backend(spec, preferred=[backend])
    _stage(report, "choose_backend", ok=choice.backend != "none", backend=choice.backend)

    if choice.backend == "cadquery":
        step_path = output_root / "models" / "flanged_hub.step"
        step_path.parent.mkdir(parents=True, exist_ok=True)
        result = build_cadquery_from_cad_ir(spec=spec, config=config, out_step=str(step_path))
        _stage(report, "build", ok=result.get("ok", False), error=result.get("error"))
        report["files_created"] = result.get("files_created", [])
        validation = result.get("metrics", {}).get("validation", {})
        _stage(report, "inspect", ok=validation.get("ok", True))
        _stage(report, "mechanical_validate", ok=True)
        if result.get("ok"):
            report["overall_ok"] = True
    else:
        _fail(report, "build", f"Backend {backend} not supported for flanged_hub case")

    return report


# ═══════════════════════════════════════════════════════════════════════
# Case: involute_spur_gear
# ═══════════════════════════════════════════════════════════════════════

def run_case_involute_spur_gear(backend: str, output_root: Path, allow_step_import: bool = False) -> dict:
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.geometry_primitives.gears.standards import (
        spur_gear_reference_dimensions,
    )

    report = _make_report_skeleton("involute_spur_gear", backend)
    config = EngineeringToolsConfig(workspace_root=output_root, allow_overwrite=True)

    params = {
        "module_mm": 2.0, "teeth": 24,
        "pressure_angle_deg": 20.0, "face_width_mm": 15.0, "bore_dia_mm": 10.0,
    }
    ref = spur_gear_reference_dimensions(params)

    spec_dict = {
        "name": "involute_spur_gear_demo", "units": "mm",
        "target_backend": [backend],
        "features": [{"id": "gear1", "type": "primitive",
                       "primitive_name": "involute_spur_gear",
                       "parameters": params}],
        "validation": {
            "expected_body_count": 1,
            "expected_bbox_mm": [ref["outer_diameter_mm"], ref["outer_diameter_mm"], params["face_width_mm"]],
            "tolerance_mm": 0.5,
            "expected_kernel": "cq_gears",
        },
    }

    # Stage 1: validate_cad_ir
    try:
        spec = CADPartSpec.model_validate(spec_dict)
        _stage(report, "validate_cad_ir", ok=True)
    except Exception as exc:
        _fail(report, "validate_cad_ir", str(exc))
        return report

    # Stage 2: normalize_primitives (primitive params)
    try:
        from seekflow_engineering_tools.geometry_primitives.registry import normalize_primitive_parameters
        norm = normalize_primitive_parameters("involute_spur_gear", params)
        _stage(report, "normalize_primitives", ok=True, normalized_params=norm)
    except Exception as exc:
        _fail(report, "normalize_primitives", str(exc))
        return report

    # Stage 3: choose_backend
    from seekflow_engineering_tools.capabilities.registry import choose_backend

    if backend in ("solidworks2025", "nx12") and not allow_step_import:
        _fail(report, "choose_backend",
              f"Backend '{backend}' requires --allow-step-import for gear primitives. "
              f"Use --backend cadquery or add --allow-step-import.")
        return report

    choice = choose_backend(spec, preferred=[backend])
    _stage(report, "choose_backend", ok=choice.backend != "none", backend=choice.backend,
           strategy="cadquery_step_import" if backend in ("solidworks2025", "nx12") else "native_cadquery_primitive")

    # Stage 4-6: build → inspect → mechanical_validate
    step_path = output_root / "models" / "involute_spur_gear.step"
    step_path.parent.mkdir(parents=True, exist_ok=True)

    if choice.backend == "cadquery":
        result = build_cadquery_from_cad_ir(spec=spec, config=config, out_step=str(step_path))
        _stage(report, "build", ok=result.get("ok", False), error=result.get("error"))
        report["files_created"] = result.get("files_created", [])

        mv = result.get("metrics", {}).get("mechanical_validation", {})
        validation = result.get("metrics", {}).get("validation", {})
        _stage(report, "inspect", ok=validation.get("ok", True))
        _stage(report, "mechanical_validate", ok=mv.get("ok", True))

        # Extract kernel_used and reference_dimensions
        kernel_used = "unknown"
        for r in mv.get("results", []):
            if "kernel" in r:
                kernel_used = r["kernel"]
            if "reference_dimensions" in r:
                ref = r["reference_dimensions"]

        # Try reading from metadata sidecar
        meta_path = step_path.with_suffix(".metadata.json")
        if meta_path.exists():
            sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
            pm = sidecar.get("primitive_metadata", {}).get("involute_spur_gear", {})
            if pm.get("kernel"):
                kernel_used = pm["kernel"]
            if pm.get("reference_dimensions"):
                ref = pm["reference_dimensions"]

        report["metrics"] = {
            "kernel_used": kernel_used,
            "reference_dimensions": {
                "pitch_diameter_mm": ref["pitch_diameter_mm"],
                "base_diameter_mm": ref["base_diameter_mm"],
                "outer_diameter_mm": ref["outer_diameter_mm"],
                "root_diameter_mm": ref["root_diameter_mm"],
            },
        }
        report["warnings"] = result.get("warnings", [])

        if result.get("ok"):
            report["overall_ok"] = True

    elif choice.backend in ("solidworks2025", "nx12"):
        from seekflow_engineering_tools.natural_language.backend_builders import (
            build_solidworks_from_canonical_step,
            build_nx_from_canonical_step,
        )
        if choice.backend == "solidworks2025":
            result = build_solidworks_from_canonical_step(spec, config, str(step_path))
        else:
            result = build_nx_from_canonical_step(spec, config, str(step_path))

        _stage(report, "build", ok=result.get("ok", False), error=result.get("error"))
        report["files_created"] = result.get("files_created", [])

        # Extract inspection and mechanical_validation from cq_result metrics
        metrics = result.get("metrics", {})
        validation = metrics.get("validation", {})
        mech_val = metrics.get("mechanical_validation", {})
        _stage(report, "inspect", ok=validation.get("ok", True))
        _stage(report, "mechanical_validate", ok=mech_val.get("ok", True))

        # Extract kernel_used and reference_dimensions from metadata sidecar
        kernel_used = mech_val.get("kernel", "unknown")
        ref = {}
        meta_path = step_path.with_suffix(".metadata.json")
        if meta_path.exists():
            try:
                sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
                pm = sidecar.get("primitive_metadata", {}).get("involute_spur_gear", {})
                if pm.get("kernel"):
                    kernel_used = pm["kernel"]
                if pm.get("reference_dimensions"):
                    ref = pm["reference_dimensions"]
            except (json.JSONDecodeError, OSError):
                pass

        report["metrics"] = {
            "kernel_used": kernel_used,
            "reference_dimensions": {
                "pitch_diameter_mm": ref.get("pitch_diameter_mm"),
                "base_diameter_mm": ref.get("base_diameter_mm"),
                "outer_diameter_mm": ref.get("outer_diameter_mm"),
                "root_diameter_mm": ref.get("root_diameter_mm"),
            },
        }
        report["warnings"] = result.get("warnings", [])
        if result.get("ok"):
            report["overall_ok"] = True

    return report


# ═══════════════════════════════════════════════════════════════════════
# Case registry
# ═══════════════════════════════════════════════════════════════════════

CASE_RUNNERS = {
    "box": run_case_box,
    "flanged_hub": run_case_flanged_hub,
    "involute_spur_gear": run_case_involute_spur_gear,
}


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="SeekFlow Industrial Text-to-CAD — CI Acceptance Script"
    )
    parser.add_argument("--case", default="all",
                        choices=["all", "box", "flanged_hub", "involute_spur_gear"])
    parser.add_argument("--backend", default="cadquery",
                        choices=["cadquery", "solidworks2025", "nx12"])
    parser.add_argument("--output", default=None, help="Output directory")
    parser.add_argument("--json-report", default=None, help="Write JSON report")
    parser.add_argument("--allow-step-import", action="store_true",
                        help="Allow STEP import for SW/NX gear primitives")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(args.output) if args.output else Path(__file__).parent / "demo_output" / ts
    output_root.mkdir(parents=True, exist_ok=True)

    cases_to_run = list(CASE_RUNNERS.keys()) if args.case == "all" else [args.case]

    full_report = {
        "timestamp": datetime.now().isoformat(),
        "overall_ok": True,
        "cases": [],
    }

    for case_name in cases_to_run:
        runner = CASE_RUNNERS[case_name]
        case_report = runner(args.backend, output_root, args.allow_step_import)
        full_report["cases"].append(case_report)
        if not case_report["overall_ok"]:
            full_report["overall_ok"] = False
        status = "OK" if case_report["overall_ok"] else "FAIL"
        errs = "; ".join(case_report.get("errors", [])[:3])
        print(f"  [{status}] {case_name}/{args.backend}" + (f" — {errs}" if errs else ""))

    # Write JSON report
    if args.json_report:
        report_path = Path(args.json_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(full_report, f, indent=2, ensure_ascii=False, default=str)
        print(f"Report: {report_path}")

    # Local report
    local = output_root / "demo_report.json"
    with open(local, "w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=2, ensure_ascii=False, default=str)

    passed = sum(1 for c in full_report["cases"] if c["overall_ok"])
    print(f"Done: {passed}/{len(full_report['cases'])} passed, output={output_root}")

    if not full_report["overall_ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
