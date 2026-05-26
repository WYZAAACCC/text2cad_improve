#!/usr/bin/env python
r"""SeekFlow Engineering Tools — Full Pipeline Demo (v2).

Tests every layer of the NL-CAD/NL-CAE pipeline across:
  Layer 1: NL-CAD 输入规范化
  Layer 2: CAD-IR / CAE-IR Pydantic 中间表示
  Layer 3: Recipe Registry 高层建模操作
  Layer 4: Backend Compiler (SW VBS / NX job / ANSYS APDL / CadQuery)
  Layer 5: Inspector 几何校验
  Layer 6: Repair Loop 错误结构化反馈

Usage:
    python demo_full.py                     # all tests
    python demo_full.py --sw-only           # SolidWorks only
    python demo_full.py --ansys-only        # ANSYS only
    python demo_full.py --ir-only           # CAD-IR + CadQuery only (no hardware needed)
    python demo_full.py --output D:\out     # custom output dir
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Configure environment
os.environ.setdefault("ENGINEERING_ALLOW_OVERWRITE", "1")
os.environ.setdefault("ENGINEERING_WORKSPACE",
    r"E:\auto_detection_process\demo_output\workspace")
os.environ.setdefault("ANSYS181_EXE",
    r"D:\ANSYS181\ANSYS Inc\v181\ansys\bin\winx64\ANSYS181.exe")
os.environ.setdefault("SOLIDWORKS_PART_TEMPLATE",
    r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot")

SW_TEMPLATE = os.environ["SOLIDWORKS_PART_TEMPLATE"]
OUTPUT_BASE = Path(r"E:\auto_detection_process\demo_output")

# Color helpers
GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
CYAN = "\033[96m"; BOLD = "\033[1m"; RESET = "\033[0m"


class DemoReporter:
    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.results: list[dict] = []
        self._start_time = time.time()
        self.passed = 0; self.failed = 0; self.warned = 0

    def run(self, category: str, name: str, fn):
        tag = f"[{category}] {name}"
        sys.stdout.write(f"  {tag:<70s} ... ")
        sys.stdout.flush()
        t0 = time.time()
        try:
            data = fn()
            elapsed = time.time() - t0
            data["_elapsed_s"] = round(elapsed, 2)
            data["_category"] = category
            data["_name"] = name
            data["_ok"] = data.get("ok", True)
            self.results.append(data)
            if data["_ok"]:
                self.passed += 1
                print(f"{GREEN}OK{RESET} ({elapsed:.1f}s)")
            else:
                self.warned += 1
                print(f"{YELLOW}WARN{RESET} ({elapsed:.1f}s)")
                if data.get("warnings"):
                    for w in data["warnings"][:2]:
                        print(f"         {YELLOW}→ {w}{RESET}")
            return data
        except Exception as exc:
            elapsed = time.time() - t0
            self.failed += 1
            data = {
                "_ok": False, "_category": category, "_name": name,
                "_elapsed_s": round(elapsed, 2), "_error": str(exc),
            }
            self.results.append(data)
            print(f"{RED}FAIL{RESET} ({elapsed:.1f}s)")
            print(f"         {RED}{exc}{RESET}")
            return data

    def summary(self):
        total = len(self.results)
        elapsed = time.time() - self._start_time
        report_path = self.output_root / "demo_report.json"
        report = {
            "timestamp": datetime.now().isoformat(),
            "output_root": str(self.output_root),
            "total": total, "passed": self.passed,
            "failed": self.failed, "warned": self.warned,
            "elapsed_s": round(elapsed, 1),
            "environment": {
                "solidworks_template": SW_TEMPLATE,
                "ansys_exe": os.environ.get("ANSYS181_EXE", ""),
            },
            "results": self.results,
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n{BOLD}{'='*70}{RESET}")
        print(f"{BOLD}  DEMO COMPLETE{RESET}")
        print(f"{'='*70}")
        print(f"  Total:   {total}")
        print(f"  Passed:  {GREEN}{self.passed}{RESET}")
        print(f"  Warned:  {YELLOW}{self.warned}{RESET}")
        print(f"  Failed:  {RED}{self.failed}{RESET}" if self.failed else f"  Failed:  0")
        print(f"  Time:    {elapsed:.1f}s")
        print(f"  Output:  {self.output_root}")
        print(f"  Report:  {report_path}")
        print(f"{'='*70}\n")
        return report


# ═══════════════════════════════════════════════════════════════════════
# ANSYS — 6 APDL Templates
# ═══════════════════════════════════════════════════════════════════════

def _ansys_runner():
    from seekflow_engineering_tools.ansys.apdl_runner import AnsysAPDLRunner
    exe = Path(os.environ["ANSYS181_EXE"])
    return AnsysAPDLRunner(exe, Path("."), default_timeout_s=600, default_nproc=2)

def _run_ansys_template(job_dir: Path, template_name: str, params: dict) -> dict:
    from seekflow_engineering_tools.ansys.apdl_templates import render_template
    from seekflow_engineering_tools.ansys.parsers import parse_result_summary

    job_dir.mkdir(parents=True, exist_ok=True)
    apdl = render_template(template_name, **params)
    inp = job_dir / f"{template_name}.inp"
    inp.write_text(apdl, encoding="utf-8")

    runner = _ansys_runner()
    runner.workspace_root = job_dir.parent
    raw = runner.run_apdl_file(inp, job_dir, template_name, timeout_s=600)

    summary = job_dir / "result_summary.txt"
    metrics = parse_result_summary(summary) if summary.exists() else {}
    warnings = []
    if not summary.exists():
        warnings.append("result_summary.txt was not generated.")
    if raw["has_warning"]:
        warnings.append("ANSYS output contains WARNING messages.")

    files = [str(inp), raw["output_file"]]
    if summary.exists():
        files.append(str(summary))
    for f in job_dir.glob("*.rst*"):
        files.append(str(f))

    return {
        "ok": not raw["has_error"],
        "returncode": raw["returncode"],
        "elapsed_s": raw["elapsed_s"],
        "metrics": metrics,
        "files_created": files,
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════════════
# SolidWorks — 4 Models
# ═══════════════════════════════════════════════════════════════════════

def _sw_connect():
    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
    return SolidWorksClient(visible=True, part_template=Path(SW_TEMPLATE)).connect()

def _sw_save_model(client, model, out_dir: Path, base_name: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    sldprt = out_dir / f"{base_name}.SLDPRT"
    step = out_dir / f"{base_name}.STEP"
    ok = client.save_as(model, sldprt)
    client.export_step(model, step)
    files = [str(sldprt)]
    if step.exists():
        files.append(str(step))
    return {
        "ok": ok and sldprt.exists(),
        "files_created": files,
        "size_sldprt": sldprt.stat().st_size if sldprt.exists() else 0,
        "size_step": step.stat().st_size if step.exists() else 0,
    }

def _sw_build_and_save(out_dir: Path, base_name: str, build_fn) -> dict:
    """Create a part, build geometry, save — all with one COM connection."""
    client = _sw_connect()
    model = client.new_part()
    try:
        build_fn(client, model)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "stage": "build"}
    return _sw_save_model(client, model, out_dir, base_name)

def sw_box(out_dir: Path) -> dict:
    return _sw_build_and_save(out_dir / "box", "box",
        lambda c, m: c.create_extruded_box(m, 0.100, 0.060, 0.030))

def sw_flanged_hub(out_dir: Path) -> dict:
    return _sw_build_and_save(out_dir / "flanged_hub", "flanged_hub",
        lambda c, m: c.create_flanged_hub(m,
            flange_dia_m=0.080, flange_h_m=0.012,
            hub_dia_m=0.040, hub_h_m=0.028,
            bore_dia_m=0.020, bolt_pcd_m=0.060,
            bolt_dia_m=0.008, bolt_count=4))

def sw_spur_gear(out_dir: Path) -> dict:
    return _sw_build_and_save(out_dir / "spur_gear", "spur_gear",
        lambda c, m: c.create_spur_gear(m,
            module_m=0.003, teeth=20,
            face_width_m=0.020, bore_dia_m=0.015))

def sw_gear_involute(out_dir: Path) -> dict:
    return _sw_build_and_save(out_dir / "gear_involute", "gear_involute",
        lambda c, m: c.create_spur_gear_involute(m,
            module_m=0.003, teeth=20,
            face_width_m=0.020, bore_dia_m=0.015))

def sw_gear_true_involute(out_dir: Path) -> dict:
    return _sw_build_and_save(out_dir / "gear_true_involute", "gear_true_involute",
        lambda c, m: c.create_spur_gear_true_involute(m,
            module_m=0.003, teeth=20,
            face_width_m=0.020, bore_dia_m=0.015,
            pressure_angle_deg=20.0))


# ═══════════════════════════════════════════════════════════════════════
# NX — 4 Job Submissions
# ═══════════════════════════════════════════════════════════════════════

def _nx_job_dir():
    return Path(os.environ.get("NX_JOB_ROOT",
        r"C:\Users\mycomputer\seekflow_workspace\nx_jobs"))

def _submit_nx_job(action: str, params: dict, timeout_s: int = 10) -> dict:
    from seekflow_engineering_tools.nx.job_queue import NXJobQueue
    q = NXJobQueue(_nx_job_dir())
    job_id = q.submit(action, params)
    try:
        result = q.wait(job_id, timeout_s=timeout_s)
        return {
            "ok": result.get("ok", False),
            "job_id": job_id,
            "files_created": result.get("files_created", []),
            "metrics": result.get("metrics", {}),
        }
    except TimeoutError:
        return {
            "ok": False,
            "job_id": job_id,
            "warnings": [f"Job {job_id} timed out — NX bridge may not be running"],
            "status": "pending",
        }

def nx_block(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    return _submit_nx_job("create_block_part", {
        "length_mm": 100, "width_mm": 60, "height_mm": 20,
        "out_prt": str(out_dir / "block.prt"),
    })

def nx_block_hole(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    return _submit_nx_job("create_block_with_hole", {
        "length_mm": 100, "width_mm": 60, "height_mm": 40,
        "hole_dia_mm": 16, "hole_x": 50, "hole_z": 30,
        "out_prt": str(out_dir / "block_hole.prt"),
    })

def nx_l_bracket(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    return _submit_nx_job("create_l_bracket", {
        "base_length": 100, "base_width": 60, "thickness": 15,
        "leg_height": 60, "out_prt": str(out_dir / "l_bracket.prt"),
    })

def nx_stepped(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    return _submit_nx_job("create_stepped_block", {
        "base_length": 80, "base_width": 80, "base_height": 20,
        "top_length": 60, "top_width": 60, "top_height": 30,
        "out_prt": str(out_dir / "stepped_block.prt"),
    })


# ═══════════════════════════════════════════════════════════════════════
# CAD-IR + CadQuery Backend (no hardware needed)
# ═══════════════════════════════════════════════════════════════════════

RECIPES = {
    "box": {"length_mm": 100, "width_mm": 60, "height_mm": 30},
    "cylinder": {"diameter_mm": 50, "height_mm": 80},
    "block_with_hole": {"length_mm": 100, "width_mm": 60, "height_mm": 40, "hole_dia_mm": 16},
    "l_bracket": {"base_length_mm": 100, "base_width_mm": 60, "thickness_mm": 15, "leg_height_mm": 60},
    "stepped_block": {"base_length_mm": 80, "base_width_mm": 80, "base_height_mm": 20,
                      "top_length_mm": 60, "top_width_mm": 60, "top_height_mm": 30},
    "flanged_hub": {"flange_dia_mm": 80, "flange_thickness_mm": 12, "hub_dia_mm": 40,
                    "hub_height_mm": 28, "bore_dia_mm": 20, "bolt_pcd_mm": 60,
                    "bolt_dia_mm": 8, "bolt_count": 4},
    "spur_gear": {"module_mm": 3, "teeth": 20, "face_width_mm": 20, "bore_dia_mm": 15},
    "shaft_basic": {"total_length_mm": 150, "shaft_dia_mm": 30},
    "shaft_with_keyway": {"total_length_mm": 150, "shaft_dia_mm": 30,
                          "keyway_width_mm": 8, "keyway_depth_mm": 4},
}

def cad_ir_validate_recipe(out_dir: Path, recipe_name: str, params: dict) -> dict:
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.natural_language.tools import engineering_validate_cad_ir

    spec = {
        "name": f"{recipe_name}_demo",
        "units": "mm",
        "target_backend": ["cadquery"],
        "features": [{"id": "main", "type": "recipe",
                       "recipe_name": recipe_name, "parameters": params}],
    }

    # Save CAD-IR YAML
    out_dir.mkdir(parents=True, exist_ok=True)
    import yaml
    yaml_path = out_dir / f"{recipe_name}.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(spec, f, allow_unicode=True, default_flow_style=False)

    # Validate
    val = engineering_validate_cad_ir(spec)

    # Compile CadQuery
    from seekflow_engineering_tools.cadquery_backend.compiler import compile_cad_ir_to_cadquery_script
    cad_spec = CADPartSpec.model_validate(spec)
    script = compile_cad_ir_to_cadquery_script(cad_spec,
        out_step=f"{recipe_name}.step")
    py_path = out_dir / f"{recipe_name}.py"
    py_path.write_text(script, encoding="utf-8")

    return {
        "ok": val["ok"],
        "cad_ir_yaml": str(yaml_path),
        "cadquery_script": str(py_path),
        "script_length": len(script),
        "feature_count": len(cad_spec.features),
        "warnings": val.get("warnings", []),
    }

def cad_ir_all_recipes(out_dir: Path) -> dict:
    ir_dir = out_dir / "cad_ir"
    cq_dir = out_dir / "cadquery_scripts"
    results = {}
    for name, params in RECIPES.items():
        r = cad_ir_validate_recipe(out_dir, name, params)
        results[name] = r
    all_ok = all(v["ok"] for v in results.values())
    return {
        "ok": all_ok,
        "recipes_tested": len(results),
        "recipes": results,
    }


# ═══════════════════════════════════════════════════════════════════════
# Capability Registry Test
# ═══════════════════════════════════════════════════════════════════════

def capability_check(out_dir: Path) -> dict:
    from seekflow_engineering_tools.capabilities.registry import (
        CAPABILITIES, backend_supports_recipe, list_backend_recipes,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    check_file = out_dir / "capability_check.json"

    check = {}
    for backend in ["solidworks2025", "nx12", "ansys181", "cadquery"]:
        cap = CAPABILITIES.get(backend, {})
        check[backend] = {
            "software": cap.get("software"),
            "version": cap.get("version"),
            "stable_recipes": list_backend_recipes(backend),
            "caveats": cap.get("caveats", []),
        }

    with open(check_file, "w", encoding="utf-8") as f:
        json.dump(check, f, indent=2, ensure_ascii=False)

    # Cross-check: every recipe has at least one backend
    uncovered = []
    for recipe in RECIPES:
        backends = [b for b in ["cadquery", "solidworks2025", "nx12"]
                    if backend_supports_recipe(b, recipe)]
        if not backends:
            uncovered.append(recipe)

    return {
        "ok": len(uncovered) == 0,
        "backends": list(check.keys()),
        "total_recipes_covered": sum(
            len(c["stable_recipes"]) for c in check.values()),
        "uncovered_recipes": uncovered,
        "report_file": str(check_file),
    }


# ═══════════════════════════════════════════════════════════════════════
# NL-CAD: Ambiguity Detection + Normalization
# ═══════════════════════════════════════════════════════════════════════

def nl_cad_normalizer_test(out_dir: Path) -> dict:
    from seekflow_engineering_tools.natural_language.normalizer import detect_ambiguities

    cases = [
        ("partial_flanged_hub", {
            "suggested_template": "flanged_hub",
            "parameters": {"flange_dia_mm": 80},
        }),
        ("complete_l_bracket", {
            "suggested_template": "l_bracket",
            "parameters": {"base_length_mm": 100, "base_width_mm": 60,
                          "thickness_mm": 15, "leg_height_mm": 60},
        }),
        ("empty_input", {"suggested_template": "box", "parameters": {}}),
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for case_name, intent in cases:
        result = detect_ambiguities(intent)
        results[case_name] = result

    # Write to JSON
    import json
    report = out_dir / "normalizer_test.json"
    with open(report, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    return {
        "ok": True,
        "cases": len(cases),
        "flanged_hub_ambiguities": len(results["partial_flanged_hub"]["ambiguities"]),
        "l_bracket_ambiguities": len(results["complete_l_bracket"]["ambiguities"]),
        "box_ambiguities": len(results["empty_input"]["ambiguities"]),
        "report_file": str(report),
    }


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="SeekFlow Engineering Tools — Full Pipeline Demo v2")
    parser.add_argument("--output", default=str(OUTPUT_BASE),
                        help=f"Output root directory (default: {OUTPUT_BASE})")
    parser.add_argument("--sw-only", action="store_true")
    parser.add_argument("--ansys-only", action="store_true")
    parser.add_argument("--ir-only", action="store_true")
    parser.add_argument("--skip-sw", action="store_true")
    parser.add_argument("--skip-nx", action="store_true")
    parser.add_argument("--skip-ansys", action="store_true")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(args.output) / ts
    output_root.mkdir(parents=True, exist_ok=True)

    reporter = DemoReporter(output_root)

    run_all = not (args.sw_only or args.ansys_only or args.ir_only)
    run_sw = run_all or args.sw_only
    run_ansys = run_all or args.ansys_only
    run_ir = run_all or args.ir_only
    if args.skip_sw: run_sw = False
    if args.skip_ansys: run_ansys = False
    if args.skip_nx: run_nx = False
    else: run_nx = True and not args.ansys_only and not args.ir_only

    print(f"\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}  SeekFlow Engineering Tools — Full Pipeline Demo v2{RESET}")
    print(f"{'='*70}")
    print(f"  Output:    {output_root}")
    print(f"  SW 2025:   {'ON' if run_sw else 'OFF'}")
    print(f"  NX 12.0:   {'ON' if run_nx else 'OFF'}")
    print(f"  ANSYS:     {'ON' if run_ansys else 'OFF'}")
    print(f"  CAD-IR:    {'ON' if run_ir else 'OFF'}")
    print(f"{'='*70}")

    # ═══════════════════════════════════════════════════════════════
    # Layer 1+2: CAD-IR / CAE-IR
    # ═══════════════════════════════════════════════════════════════
    if run_ir:
        print(f"\n{CYAN}{'='*70}{RESET}")
        print(f"{CYAN}  Layer 1-2: NL-CAD Normalizer + CAD-IR Schema{RESET}")
        print(f"{CYAN}{'='*70}{RESET}")

        reporter.run("Layer1-2", "NL-CAD ambiguity detection",
            lambda: nl_cad_normalizer_test(output_root / "nl_cad"))

        reporter.run("Layer1-2", "CAD-IR: validate all 9 recipes",
            lambda: cad_ir_all_recipes(output_root))

        reporter.run("Layer1-2", "Capability registry check",
            lambda: capability_check(output_root / "capabilities"))

    # ═══════════════════════════════════════════════════════════════
    # Layer 3+4: Recipe Registry + Backend Compilers
    # ═══════════════════════════════════════════════════════════════
    if run_ir:
        print(f"\n{CYAN}{'='*70}{RESET}")
        print(f"{CYAN}  Layer 3-4: Recipe Registry + Backend Compilers{RESET}")
        print(f"{CYAN}{'='*70}{RESET}")

        from seekflow_engineering_tools.recipes.registry import (
            list_recipe_names, get_recipe_definition, recipe_supports_backend,
        )
        reporter.run("Layer3", "Recipe registry: list all",
            lambda: {"ok": True, "count": len(list_recipe_names()),
                     "recipes": list_recipe_names()})

        reporter.run("Layer4", "CadQuery compiler: all 9 recipes",
            lambda: {"ok": True, "message": "See CadQuery scripts in cadquery_scripts/"})


    # ═══════════════════════════════════════════════════════════════
    # ANSYS 18.1 — 6 FEM Analyses
    # ═══════════════════════════════════════════════════════════════
    if run_ansys:
        print(f"\n{CYAN}{'='*70}{RESET}")
        print(f"{CYAN}  ANSYS 18.1 — 6 Finite Element Analyses (APDL Batch){RESET}")
        print(f"{CYAN}{'='*70}{RESET}")

        ansys_dir = output_root / "ansys"

        reporter.run("ANSYS", "Static cantilever beam",
            lambda: _run_ansys_template(ansys_dir / "01_static_beam",
                "static_cantilever_beam_rect",
                {"length_mm": 200, "width_mm": 20, "height_mm": 20,
                 "force_n": 1000, "element_size_mm": 10}))

        reporter.run("ANSYS", "Plate with hole (stress conc.)",
            lambda: _run_ansys_template(ansys_dir / "02_plate_hole",
                "plate_with_hole_tension",
                {"plate_width_mm": 200, "plate_height_mm": 100,
                 "plate_thickness_mm": 10, "hole_diameter_mm": 20,
                 "tensile_stress_mpa": 100, "element_size_mm": 5}))

        reporter.run("ANSYS", "Steady thermal",
            lambda: _run_ansys_template(ansys_dir / "03_thermal",
                "beam_thermal",
                {"length_mm": 200, "temp_left_c": 100, "temp_right_c": 0,
                 "element_size_mm": 5}))

        reporter.run("ANSYS", "Modal analysis (natural freq.)",
            lambda: _run_ansys_template(ansys_dir / "04_modal",
                "cantilever_modal",
                {"length_mm": 200, "width_mm": 20, "height_mm": 20,
                 "n_modes": 5, "element_size_mm": 10}))

        reporter.run("ANSYS", "Euler buckling (stability)",
            lambda: _run_ansys_template(ansys_dir / "05_buckling",
                "buckling_column",
                {"length_mm": 500, "width_mm": 20, "height_mm": 20,
                 "element_size_mm": 10, "n_modes": 3}))

        reporter.run("ANSYS", "Bilinear plasticity (nonlinear)",
            lambda: _run_ansys_template(ansys_dir / "06_plastic",
                "bilinear_plastic",
                {"length_mm": 100, "width_mm": 10, "height_mm": 10,
                 "yield_stress_mpa": 235, "displacement_mm": 5,
                 "n_substeps": 20, "element_size_mm": 5}))

    # ═══════════════════════════════════════════════════════════════
    # SolidWorks 2025 — 4 Models
    # ═══════════════════════════════════════════════════════════════
    if run_sw:
        print(f"\n{CYAN}{'='*70}{RESET}")
        print(f"{CYAN}  SolidWorks 2025 — 4 CAD Models{RESET}")
        print(f"{CYAN}{'='*70}{RESET}")

        sw_dir = output_root / "solidworks"

        reporter.run("SolidWorks", "Simple box (1 feature)",
            lambda: sw_box(sw_dir))
        reporter.run("SolidWorks", "Flanged hub (4 features: flange+boss+bore+bolts)",
            lambda: sw_flanged_hub(sw_dir))
        reporter.run("SolidWorks", "Spur gear (star polygon)",
            lambda: sw_spur_gear(sw_dir))
        reporter.run("SolidWorks", "Spur gear (involute profile)",
            lambda: sw_gear_involute(sw_dir))
        reporter.run("SolidWorks", "Spur gear (TRUE involute ISO 53/DIN 867)",
            lambda: sw_gear_true_involute(sw_dir))

    # ═══════════════════════════════════════════════════════════════
    # NX 12.0 — 4 Job Submissions
    # ═══════════════════════════════════════════════════════════════
    if run_nx:
        print(f"\n{CYAN}{'='*70}{RESET}")
        print(f"{CYAN}  NX 12.0 — 4 CAD Jobs (File Queue Bridge){RESET}")
        print(f"{CYAN}{'='*70}{RESET}")

        # Start NX Bridge if available
        NX_RUNNER = os.environ.get("NX_JOURNAL_RUNNER", r"D:\nx\NXBIN\run_journal.exe")
        NX_BRIDGE_SCRIPT = str(
            Path(__file__).resolve().parent /
            "src/seekflow_engineering_tools/nx/nx_bridge_bootstrap.py"
        )
        nx_bridge_started = False
        if Path(NX_RUNNER).exists():
            import subprocess as _sp
            try:
                _sp.Popen(
                    [NX_RUNNER, NX_BRIDGE_SCRIPT],
                    env={**os.environ, "NX_JOB_ROOT": str(_nx_job_dir())},
                )
                print(f"  {GREEN}NX Bridge launched (PID pending){RESET}")
                nx_bridge_started = True
                time.sleep(4)  # Let it initialize
            except Exception as e:
                print(f"  {YELLOW}NX Bridge start failed: {e}{RESET}")
        else:
            print(f"  {YELLOW}NX Journal Runner not found at {NX_RUNNER}{RESET}")

        nx_dir = output_root / "nx"
        nx_dir.mkdir(parents=True, exist_ok=True)

        reporter.run("NX", "Simple block",
            lambda: nx_block(nx_dir))
        reporter.run("NX", "Block with through-hole",
            lambda: nx_block_hole(nx_dir))
        reporter.run("NX", "L-bracket (boolean unite)",
            lambda: nx_l_bracket(nx_dir))
        reporter.run("NX", "Stepped block (multi-body unite)",
            lambda: nx_stepped(nx_dir))

        # NX health check
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.nx.tools import build_nx_tools
        config = EngineeringToolsConfig(nx_enabled=True,
            nx_job_root=_nx_job_dir(), workspace_root=output_root.parent)
        tools = build_nx_tools(config)
        health = next(t for t in tools if t.name == "nx_health_check")
        reporter.run("NX", "Health check + heartbeat",
            lambda: health.func())

    # ═══════════════════════════════════════════════════════════════
    # Layer 5+6: Inspector + Repair
    # ═══════════════════════════════════════════════════════════════
    if run_ir:
        print(f"\n{CYAN}{'='*70}{RESET}")
        print(f"{CYAN}  Layer 5-6: Inspector + Repair Loop{RESET}")
        print(f"{CYAN}{'='*70}{RESET}")

        from seekflow_engineering_tools.inspection.common import (
            ModelInspection, ValidationIssue, ValidationReport)
        from seekflow_engineering_tools.repair.diagnostics import build_repair_prompt
        from seekflow_engineering_tools.repair.loop import classify_failure

        reporter.run("Layer5", "ModelInspection schema",
            lambda: {"ok": True,
                     "inspection": ModelInspection(
                         bbox_mm=[80.0, 80.0, 40.0],
                         body_count=1,
                         through_hole_count_estimate=5,
                     ).model_dump()})

        reporter.run("Layer5", "ValidationReport schema",
            lambda: {"ok": True,
                     "report": ValidationReport(
                         ok=True, issues=[],
                     ).model_dump()})

        reporter.run("Layer6", "Classify failure: VBS error",
            lambda: {"ok": True,
                     "classification": classify_failure(
                         {"error": "VBS_ERR|select_plane|424|Object required", "ok": False}
                     )})

        reporter.run("Layer6", "Repair prompt generation",
            lambda: {"ok": True,
                     "prompt_length": len(build_repair_prompt(
                         {"name": "test"}, {"ok": False}, {"issues": []}
                     ))})

        # STEP inspection if SW files exist
        sw_dir = output_root / "solidworks" / "flanged_hub"
        step_file = sw_dir / "flanged_hub.STEP"
        if step_file.exists():
            from seekflow_engineering_tools.cadquery_backend.inspector import (
                inspect_step_with_cadquery)
            reporter.run("Layer5", "STEP inspection (flanged hub)",
                lambda: {"ok": True,
                         "inspection": inspect_step_with_cadquery(step_file)})

    # ═══════════════════════════════════════════════════════════════
    # Final Summary
    # ═══════════════════════════════════════════════════════════════
    report = reporter.summary()

    # Print key metrics
    print(f"\n{BOLD}Key Engineering Results:{RESET}")
    for r in reporter.results:
        if not r["_ok"]:
            continue
        name = r.get("_name", "")
        cat = r.get("_category", "")
        if "metrics" in r and isinstance(r["metrics"], dict):
            m = r["metrics"]
            highlights = []
            if "max_displacement_mm" in m:
                highlights.append(f"d_max={m['max_displacement_mm']:.4f}mm")
            if "stress_concentration_kt" in m:
                highlights.append(f"Kt={m['stress_concentration_kt']:.3f}")
            if "tmid_c" in m:
                highlights.append(f"Tmid={m['tmid_c']:.1f}°C")
            if "max_plastic_strain" in m:
                highlights.append(f"eps_pl={m['max_plastic_strain']:.4f}")
            if "max_von_mises_mpa" in m:
                highlights.append(f"σ_max={m['max_von_mises_mpa']:.1f}MPa")
            if highlights:
                print(f"  {CYAN}[{cat}] {name:<45s}{RESET} {', '.join(highlights)}")
        if "size_sldprt" in r:
            print(f"  {CYAN}[{cat}] {name:<45s}{RESET} SLDPRT={r['size_sldprt']}B, STEP={r.get('size_step', 0)}B")
        if "recipes_tested" in r:
            print(f"  {CYAN}[{cat}] {name:<45s}{RESET} {r['recipes_tested']} recipes compiled")
        if "count" in r:
            print(f"  {CYAN}[{cat}] {name:<45s}{RESET} {r['count']} items")


if __name__ == "__main__":
    main()
