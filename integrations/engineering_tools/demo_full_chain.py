#!/usr/bin/env python
r"""SeekFlow Engineering Tools — Industrial Text-to-CAD Full Chain Demo.

Runs full pipeline: CAD-IR → primitive/normalize → backend → build → inspect → validate.

Usage:
    python demo_full_chain.py
    python demo_full_chain.py --case box --backend cadquery
    python demo_full_chain.py --case flanged_hub --backend cadquery
    python demo_full_chain.py --case involute_spur_gear --backend cadquery
    python demo_full_chain.py --case all --backend cadquery --json-report reports/full_chain.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path


def _build_box(out_dir: Path, backend: str) -> dict:
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    config = EngineeringToolsConfig(workspace_root=out_dir, allow_overwrite=True)
    spec = CADPartSpec.model_validate({
        "name": "box_demo", "units": "mm",
        "target_backend": ["cadquery"],
        "features": [{"id": "main", "type": "recipe", "recipe_name": "box",
                       "parameters": {"length_mm": 100, "width_mm": 50, "height_mm": 25}}],
        "validation": {"expected_bbox_mm": [100, 50, 25], "expected_body_count": 1, "tolerance_mm": 2.0},
    })

    step_path = out_dir / "box.step"
    result = build_cadquery_from_cad_ir(spec=spec, config=config, out_step=str(step_path))

    return {
        "ok": result.get("ok", False),
        "case": "box",
        "backend": backend,
        "files_created": result.get("files_created", []),
        "metrics": result.get("metrics", {}),
        "warnings": result.get("warnings", []),
    }


def _build_flanged_hub(out_dir: Path, backend: str) -> dict:
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    config = EngineeringToolsConfig(workspace_root=out_dir, allow_overwrite=True)
    spec = CADPartSpec.model_validate({
        "name": "flanged_hub_demo", "units": "mm",
        "target_backend": ["cadquery"],
        "features": [{"id": "main", "type": "recipe", "recipe_name": "flanged_hub",
                       "parameters": {"flange_dia_mm": 80, "flange_thickness_mm": 10,
                                       "hub_dia_mm": 40, "hub_height_mm": 30,
                                       "bore_dia_mm": 20, "bolt_pcd_mm": 60,
                                       "bolt_dia_mm": 8, "bolt_count": 4}}],
        "validation": {"expected_body_count": 1},
    })

    step_path = out_dir / "flanged_hub.step"
    result = build_cadquery_from_cad_ir(spec=spec, config=config, out_step=str(step_path))

    return {
        "ok": result.get("ok", False),
        "case": "flanged_hub",
        "backend": backend,
        "files_created": result.get("files_created", []),
        "metrics": result.get("metrics", {}),
        "warnings": result.get("warnings", []),
    }


def _build_involute_spur_gear(out_dir: Path, backend: str) -> dict:
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.geometry_primitives.gears.standards import (
        spur_gear_reference_dimensions,
    )

    config = EngineeringToolsConfig(workspace_root=out_dir, allow_overwrite=True)

    params = {
        "module_mm": 2.0,
        "teeth": 24,
        "pressure_angle_deg": 20.0,
        "face_width_mm": 15.0,
        "bore_dia_mm": 10.0,
    }

    ref = spur_gear_reference_dimensions(params)

    spec = CADPartSpec.model_validate({
        "name": "involute_spur_gear_demo", "units": "mm",
        "target_backend": ["cadquery"],
        "features": [{
            "id": "gear1",
            "type": "primitive",
            "primitive_name": "involute_spur_gear",
            "parameters": params,
        }],
        "validation": {
            "expected_body_count": 1,
            "expected_bbox_mm": [ref["outer_diameter_mm"], ref["outer_diameter_mm"], params["face_width_mm"]],
            "tolerance_mm": 0.5,
            "expected_kernel": "cq_gears",
        },
    })

    step_path = out_dir / "models" / "involute_spur_gear.step"
    result = build_cadquery_from_cad_ir(spec=spec, config=config, out_step=str(step_path))

    # Extract kernel metadata — read from the metadata sidecar file
    kernel_used = "unknown"
    metadata_path = out_dir / "models" / "involute_spur_gear.metadata.json"
    if metadata_path.exists():
        import json
        with open(metadata_path, encoding="utf-8") as f:
            sidecar = json.load(f)
        pm = sidecar.get("primitive_metadata", {})
        gear_meta = pm.get("involute_spur_gear", {})
        kernel_used = gear_meta.get("kernel", "unknown")

    mv = result.get("metrics", {}).get("mechanical_validation", {})
    for r in mv.get("results", []):
        if "kernel" in r and r["kernel"] != "unknown":
            kernel_used = r["kernel"]
        if "reference_dimensions" in r:
            ref = r["reference_dimensions"]

    return {
        "ok": result.get("ok", False),
        "case": "involute_spur_gear",
        "backend": backend,
        "stages": {
            "validate_cad_ir": {"ok": True},
            "normalize_primitives": {"ok": True},
            "choose_backend": {"ok": True, "backend": backend},
            "build": {"ok": result.get("ok", False)},
            "inspect": {"ok": result.get("metrics", {}).get("validation", {}).get("ok", True)},
            "mechanical_validate": {"ok": mv.get("ok", True)},
        },
        "files_created": result.get("files_created", []),
        "metrics": {
            "kernel_used": kernel_used,
            "reference_dimensions": {
                "pitch_diameter_mm": ref["pitch_diameter_mm"],
                "base_diameter_mm": ref["base_diameter_mm"],
                "outer_diameter_mm": ref["outer_diameter_mm"],
                "root_diameter_mm": ref["root_diameter_mm"],
            },
        },
        "warnings": result.get("warnings", []),
    }


# ── Case registry ──

CASE_BUILDERS = {
    "box": _build_box,
    "flanged_hub": _build_flanged_hub,
    "involute_spur_gear": _build_involute_spur_gear,
}


def main():
    parser = argparse.ArgumentParser(
        description="SeekFlow Industrial Text-to-CAD — Full Chain Demo"
    )
    parser.add_argument(
        "--case", default="all",
        choices=["all", "box", "flanged_hub", "involute_spur_gear"],
        help="Which case to build (default: all)",
    )
    parser.add_argument(
        "--backend", default="cadquery",
        choices=["cadquery", "solidworks2025", "nx12"],
        help="Target backend (default: cadquery)",
    )
    parser.add_argument(
        "--json-report", default=None,
        help="Write JSON report to this path",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output directory for generated files",
    )
    parser.add_argument(
        "--allow-step-import", action="store_true",
        help="Allow STEP import strategy for SW/NX (default: only cadquery native)",
    )
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(args.output) if args.output else Path(__file__).parent / "demo_output" / ts
    output_root.mkdir(parents=True, exist_ok=True)

    # Validate backend
    if args.backend != "cadquery" and not args.allow_step_import:
        print(
            f"Backend '{args.backend}' requires --allow-step-import for primitive features. "
            f"Gear primitives for SW/NX use cadquery_step_import strategy."
        )
        if args.case == "involute_spur_gear":
            print(
                "Use --backend cadquery for native gear primitive build, "
                "or add --allow-step-import."
            )
            sys.exit(1)

    cases_to_run = list(CASE_BUILDERS.keys()) if args.case == "all" else [args.case]
    report = {
        "timestamp": datetime.now().isoformat(),
        "overall_ok": True,
        "cases": [],
    }

    for case_name in cases_to_run:
        builder = CASE_BUILDERS[case_name]
        case_dir = output_root / case_name
        case_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.time()
        try:
            result = builder(case_dir, args.backend)
            result["_elapsed_s"] = round(time.time() - t0, 2)
            report["cases"].append(result)
            status = "OK" if result["ok"] else "FAIL"
            print(f"  [{status}] {case_name} ({result['_elapsed_s']}s)")

            if not result["ok"]:
                report["overall_ok"] = False
                if result.get("warnings"):
                    for w in result["warnings"]:
                        print(f"    WARNING: {w}")
        except Exception as exc:
            elapsed = time.time() - t0
            err_result = {
                "ok": False, "case": case_name, "backend": args.backend,
                "_elapsed_s": round(elapsed, 2), "_error": str(exc),
            }
            report["cases"].append(err_result)
            report["overall_ok"] = False
            print(f"  [FAIL] {case_name} ({elapsed:.1f}s) — {exc}")

    # Write JSON report
    if args.json_report:
        report_path = Path(args.json_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nReport written to: {report_path}")

    # Also write local report
    local_report = output_root / "demo_report.json"
    with open(local_report, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"Local report: {local_report}")

    print(f"\n{'='*60}")
    print(f"  Demo Complete — overall_ok: {report['overall_ok']}")
    print(f"  Cases: {len(report['cases'])}")
    print(f"  Output: {output_root}")
    print(f"{'='*60}")

    if not report["overall_ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
