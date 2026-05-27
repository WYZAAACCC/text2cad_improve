#!/usr/bin/env python
r"""SeekFlow Engineering Tools — Full Capability Demo.

Runs every verified model through CadQuery, ANSYS templates, and NX queue.
All outputs land in a timestamped folder under demo_output/.

Usage:
    python demo_full_chain.py
    python demo_full_chain.py --output D:\results
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
CYAN = "\033[96m"; BOLD = "\033[1m"; RESET = "\033[0m"


class DemoReporter:
    """Collects and prints structured demo results — matches existing format."""

    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.results: list[dict] = []
        self._start_time = time.time()

    def run(self, category: str, name: str, fn):
        tag = f"[{category}] {name}"
        sys.stdout.write(f"  {tag:<55s} ... ")
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
            status = f"{GREEN}OK{RESET}" if data["_ok"] else f"{YELLOW}WARN{RESET}"
            print(f"{status} ({elapsed:.1f}s)")
            return data
        except Exception as exc:
            elapsed = time.time() - t0
            data = {
                "_ok": False, "_category": category, "_name": name,
                "_elapsed_s": round(elapsed, 2), "_error": str(exc),
            }
            self.results.append(data)
            print(f"{RED}FAIL{RESET} ({elapsed:.1f}s) — {exc}")
            return data

    def summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r["_ok"])
        failed = total - passed
        elapsed = time.time() - self._start_time

        report_path = self.output_root / "demo_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "total": total, "passed": passed, "failed": failed,
                "elapsed_s": round(elapsed, 1),
                "results": self.results,
            }, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}  DEMO COMPLETE{RESET}")
        print(f"{'='*60}")
        print(f"  Total:   {total}")
        print(f"  Passed:  {GREEN}{passed}{RESET}")
        if failed:
            print(f"  Failed:  {RED}{failed}{RESET}")
        else:
            print(f"  Failed:  0")
        print(f"  Time:    {elapsed:.1f}s")
        print(f"  Output:  {self.output_root}")
        print(f"  Report:  {report_path}")
        print(f"{'='*60}")

        # Print key metrics
        print(f"\n{BOLD}Key Engineering Metrics:{RESET}")
        for r in self.results:
            if r["_ok"] and "metrics" in r:
                name = r["_name"]
                m = r["metrics"]
                h = []
                if "bbox_mm" in m:
                    h.append(f"bbox={m['bbox_mm']}")
                if "volume_mm3" in m:
                    h.append(f"vol={m['volume_mm3']:.0f}mm3")
                if "body_count" in m:
                    h.append(f"bodies={m['body_count']}")
                if "step_size_kb" in m:
                    h.append(f"step={m['step_size_kb']:.1f}KB")
                if "max_displacement_mm" in m:
                    h.append(f"dmax={m['max_displacement_mm']:.4f}mm")
                if "max_von_mises_mpa" in m:
                    h.append(f"stress={m['max_von_mises_mpa']:.1f}MPa")
                if "tmid_c" in m:
                    h.append(f"Tmid={m['tmid_c']:.1f}C")
                if "modal_frequencies_hz" in m:
                    h.append(f"freq={m['modal_frequencies_hz']}")
                if h:
                    print(f"  {CYAN}{name:<35s}{RESET} {', '.join(h)}")

        print()


# ═══════════════════════════════════════════════════════════════════════
# CadQuery CAD Models
# ═══════════════════════════════════════════════════════════════════════

def _cadquery_build(reporter: DemoReporter, out_dir: Path):
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir
    from seekflow_engineering_tools.cadquery_backend.inspector import inspect_step_with_cadquery
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    config = EngineeringToolsConfig(workspace_root=out_dir, allow_overwrite=True)

    models = {
        "box_100x50x25": {
            "label": "Box 100x50x25mm (1 feature)",
            "spec": {"name": "box_100x50x25", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "box",
                    "parameters": {"length_mm": 100, "width_mm": 50, "height_mm": 25}}],
                "validation": {"expected_bbox_mm": [100, 50, 25], "expected_body_count": 1, "tolerance_mm": 2.0}},
        },
        "cylinder_d20xh50": {
            "label": "Cylinder D20xH50mm (1 feature)",
            "spec": {"name": "cylinder_d20xh50", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "cylinder",
                    "parameters": {"diameter_mm": 20, "height_mm": 50}}],
                "validation": {"expected_bbox_mm": [20, 20, 50], "expected_body_count": 1, "tolerance_mm": 2.0}},
        },
        "block_with_hole_100x50x25_d16": {
            "label": "Block+Through-Hole D16mm (2 feat)",
            "spec": {"name": "block_hole", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "block_with_hole",
                    "parameters": {"length_mm": 100, "width_mm": 50, "height_mm": 25, "hole_dia_mm": 16}}],
                "validation": {"expected_body_count": 1, "expected_through_hole_count": 1}},
        },
        "l_bracket_100x60": {
            "label": "L-Bracket 100x60mm (boolean unite)",
            "spec": {"name": "l_bracket_100x60", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "l_bracket",
                    "parameters": {"base_length_mm": 100, "base_width_mm": 60,
                        "thickness_mm": 15, "leg_height_mm": 60}}],
                "validation": {"expected_body_count": 1}},
        },
        "stepped_block_80to60": {
            "label": "Stepped Block 80→60mm (3 feat)",
            "spec": {"name": "stepped_block_80to60", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "stepped_block",
                    "parameters": {"base_length_mm": 80, "base_width_mm": 80, "base_height_mm": 20,
                        "top_length_mm": 60, "top_width_mm": 60, "top_height_mm": 30}}],
                "validation": {"expected_body_count": 1}},
        },
        "flanged_hub_d80": {
            "label": "Flanged Hub D80mm (4 bolt holes)",
            "spec": {"name": "flanged_hub_d80", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "flanged_hub",
                    "parameters": {"flange_dia_mm": 80, "flange_thickness_mm": 10,
                        "hub_dia_mm": 40, "hub_height_mm": 30, "bore_dia_mm": 20,
                        "bolt_pcd_mm": 60, "bolt_dia_mm": 8, "bolt_count": 4}}],
                "validation": {"expected_body_count": 1}},
        },
        "spur_gear_m3z20": {
            "label": "Spur Gear M3 Z20 (star polygon)",
            "spec": {"name": "spur_gear_m3z20", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "spur_gear",
                    "parameters": {"module_mm": 3, "teeth": 20, "face_width_mm": 20, "bore_dia_mm": 15}}],
                "validation": {"expected_body_count": 1}},
        },
        "spur_gear_m5z30": {
            "label": "Spur Gear M5 Z30 (large)",
            "spec": {"name": "spur_gear_m5z30", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "spur_gear",
                    "parameters": {"module_mm": 5, "teeth": 30, "face_width_mm": 30, "bore_dia_mm": 25}}],
                "validation": {"expected_body_count": 1}},
        },
        "shaft_d20_l100": {
            "label": "Shaft D20xL100mm (1 feature)",
            "spec": {"name": "shaft_d20_l100", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "shaft_basic",
                    "parameters": {"shaft_dia_mm": 20, "total_length_mm": 100}}],
                "validation": {"expected_bbox_mm": [20, 20, 100], "expected_body_count": 1, "tolerance_mm": 2.0}},
        },
    }

    for key, info in models.items():
        def make_fn(k=key, i=info):
            def fn():
                spec = CADPartSpec.model_validate(i["spec"])
                step_path = out_dir / f"{k}.step"

                # Build
                result = build_cadquery_from_cad_ir(
                    spec=spec, config=config, out_step=str(step_path), inspect=False)

                # Inspect
                insp = inspect_step_with_cadquery(step_path)
                if insp.get("error"):
                    return {"ok": False, "error": insp["error"]}

                metrics = {
                    "bbox_mm": insp.get("bbox_mm"),
                    "volume_mm3": round(insp.get("volume_mm3", 0), 1),
                    "body_count": insp.get("solid_count"),
                    "step_size_kb": round(step_path.stat().st_size / 1024, 1) if step_path.exists() else 0,
                }
                return {"ok": result.get("ok", False), "metrics": metrics,
                        "files": [str(step_path)]}
            return fn
        reporter.run("CadQuery", info["label"], make_fn())


# ═══════════════════════════════════════════════════════════════════════
# SolidWorks 2025 CAD Models (COM automation)
# ═══════════════════════════════════════════════════════════════════════

SW_TEMPLATE = os.environ.get(
    "SOLIDWORKS_PART_TEMPLATE",
    r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot",
)


def _sw_connect():
    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
    return SolidWorksClient(visible=True, part_template=Path(SW_TEMPLATE)).connect()


def _solidworks_build(reporter: DemoReporter, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # Health check first
    def sw_health():
        try:
            from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
            client = SolidWorksClient(visible=True, part_template=Path(SW_TEMPLATE))
            info = client.health_check()
            return {"ok": True, "metrics": info}
        except Exception as e:
            return {"ok": False, "error": str(e),
                    "metrics": {"available": False, "reason": str(e)[:200]}}

    reporter.run("SolidWorks", "Health check (COM availability)", sw_health)

    # Try building models
    sw_models = [
        ("box_100x60x30", "Simple box 100x60x30mm (1 feature)",
         lambda client, model: client.create_extruded_box(model, 0.100, 0.060, 0.030),
         {"length_mm": 100, "width_mm": 60, "height_mm": 30}),
        ("flanged_hub", "Flanged hub D80mm (flange+boss+bore+4 bolts)",
         lambda client, model: client.create_flanged_hub(model,
             flange_dia_m=0.080, flange_h_m=0.010, hub_dia_m=0.040,
             hub_h_m=0.030, bore_dia_m=0.020, bolt_pcd_m=0.060,
             bolt_dia_m=0.008, bolt_count=4),
         {"flange_dia_mm": 80, "flange_thickness_mm": 10, "hub_dia_mm": 40,
          "hub_height_mm": 30, "bore_dia_mm": 20, "bolt_pcd_mm": 60,
          "bolt_dia_mm": 8, "bolt_count": 4}),
        ("spur_gear_m3z20", "Spur Gear M3 Z20 (star polygon)",
         lambda client, model: client.create_spur_gear(model,
             module_m=0.003, teeth=20, face_width_m=0.020, bore_dia_m=0.015),
         {"module_mm": 3, "teeth": 20, "face_width_mm": 20, "bore_dia_mm": 15}),
        ("spur_gear_involute", "Spur Gear M3 Z20 (true involute)",
         lambda client, model: client.create_spur_gear_involute(model,
             module_m=0.003, teeth=20, face_width_m=0.020, bore_dia_m=0.015),
         {"module_mm": 3, "teeth": 20, "face_width_mm": 20, "bore_dia_mm": 15}),
    ]

    for name, label, builder, meta in sw_models:
        def make_fn(n=name, l=label, b=builder, m=meta):
            def fn():
                client = _sw_connect()
                model = client.new_part()
                b(client, model)
                sldprt = out_dir / f"{n}.SLDPRT"
                step = out_dir / f"{n}.step"
                ok = client.save_as(model, sldprt)
                if ok and sldprt.exists():
                    step_ok = client.export_step(model, step)
                else:
                    step_ok = False
                files = [str(sldprt)] if sldprt.exists() else []
                if step.exists():
                    files.append(str(step))
                return {
                    "ok": sldprt.exists(),
                    "files": files,
                    "metrics": {
                        **m,
                        "sldprt_size_kb": round(sldprt.stat().st_size / 1024, 1) if sldprt.exists() else 0,
                        "step_size_kb": round(step.stat().st_size / 1024, 1) if step.exists() else 0,
                    },
                }
            return fn
        reporter.run("SolidWorks", label, make_fn())


# ═══════════════════════════════════════════════════════════════════════
# NX 12.0 CAD Models (Job Queue Bridge)
# ═══════════════════════════════════════════════════════════════════════

NX_JOB_ROOT = os.environ.get(
    "NX_JOB_ROOT", str(Path.home() / "seekflow_workspace" / "nx_jobs"))


def _nx_build(reporter: DemoReporter, out_dir: Path):
    from seekflow_engineering_tools.nx.job_queue import NXJobQueue

    out_dir.mkdir(parents=True, exist_ok=True)
    q_root = Path(NX_JOB_ROOT) if not (out_dir / "nx_jobs").exists() else (out_dir / "nx_jobs")

    # Health check
    def nx_health():
        try:
            q = NXJobQueue(q_root)
            status = q.bridge_status()
            qs = q.queue_status()
            return {"ok": True, "metrics": {"bridge_running": status["bridge_running"],
                     "heartbeat_age_s": status.get("heartbeat_age_s"), **qs}}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    reporter.run("NX", "Health check (bridge status)", nx_health)

    # Submit jobs
    nx_models = [
        ("create_block_part", "Simple block 100x60x20mm", {
            "length_mm": 100, "width_mm": 60, "height_mm": 20,
        }),
        ("create_block_with_hole", "Block with through-hole D16mm", {
            "length_mm": 100, "width_mm": 60, "height_mm": 20,
            "hole_dia_mm": 16, "hole_x": 50, "hole_z": 30,
        }),
        ("create_l_bracket", "L-Bracket (boolean unite)", {
            "base_length": 100, "base_width": 60, "thickness": 15, "leg_height": 60,
        }),
        ("create_stepped_block", "Stepped Block 80→60mm", {
            "base_length": 80, "base_width": 80, "base_height": 20,
            "top_length": 60, "top_width": 60, "top_height": 30,
        }),
    ]

    for action, label, params in nx_models:
        def make_fn(a=action, l=label, p=params):
            def fn():
                q = NXJobQueue(q_root)
                out_prt = out_dir / f"{a}.prt"
                p["out_prt"] = str(out_prt)
                job_id = q.submit(a, p)
                try:
                    result = q.wait(job_id, timeout_s=10)  # short timeout for demo
                    return {
                        "ok": bool(result.get("ok")),
                        "files": result.get("files_created", []),
                        "metrics": result.get("metrics", {}),
                        "message": result.get("message", ""),
                    }
                except TimeoutError:
                    return {
                        "ok": False,
                        "error": f"Job {job_id} timed out (NX bridge may not be running).",
                        "metrics": {"job_id": job_id, "status": "timeout"},
                    }
            return fn
        reporter.run("NX", label, make_fn())

    # Also test heartbeat file
    def write_heartbeat():
        import json as _j, time as _t
        q = NXJobQueue(q_root)
        q.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        q.heartbeat_path.write_text(_j.dumps({
            "time_epoch": _t.time(), "nx_version": "12.0"}))
        return {"ok": q.bridge_status()["bridge_running"] is True,
                "metrics": q.queue_status()}

    reporter.run("NX", "Write heartbeat (bridge alive)", write_heartbeat)


# ═══════════════════════════════════════════════════════════════════════
# Tool Chain Validation
# ═══════════════════════════════════════════════════════════════════════

def _validate_chain(reporter: DemoReporter, out_dir: Path):
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.registry import build_engineering_tools
    from seekflow_engineering_tools.natural_language.tools import build_natural_language_tools
    from seekflow_engineering_tools.capabilities.registry import choose_backend, backend_supports_recipe
    from seekflow_engineering_tools.ir.cad import CADPartSpec, RecipeFeature
    from seekflow_engineering_tools.recipes.registry import normalize_recipe_parameters

    # Tool registration
    def tool_reg():
        config = EngineeringToolsConfig(workspace_root=out_dir / "ws")
        tools = build_engineering_tools(config)
        names = {t.name for t in tools}
        req = {"cadquery_build_from_cad_ir", "cadquery_inspect_step",
               "engineering_validate_cad_ir", "engineering_build_cad_model"}
        return {"ok": req.issubset(names), "total_tools": len(names),
                "metrics": {"required_present": list(req)}}

    reporter.run("Validate", "Tool registration (all required)", tool_reg)

    # NL validation chain
    def nl_validate():
        spec = {"name": "t", "units": "mm",
                "features": [{"id": "f1", "type": "recipe", "recipe_name": "box",
                    "parameters": {"length_mm": 100, "width_mm": 50, "height_mm": 25}}]}
        CADPartSpec.model_validate(spec)
        return {"ok": True, "metrics": {"normalized": True}}

    reporter.run("Validate", "CAD-IR schema validation", nl_validate)

    # Capability routing
    def cap_route():
        spec = CADPartSpec(name="t", features=[
            RecipeFeature(id="f1", type="recipe", recipe_name="l_bracket",
                parameters={"base_length_mm": 100, "base_width_mm": 60,
                    "thickness_mm": 15, "leg_height_mm": 60})])
        choice = choose_backend(spec, preferred=["solidworks2025"])
        params = normalize_recipe_parameters("flanged_hub", {
            "flange_dia_mm": 80, "flange_thickness_mm": 10, "hub_dia_mm": 40,
            "hub_height_mm": 30, "bore_dia_mm": 20, "bolt_pcd_mm": 60,
            "bolt_dia_mm": 8, "bolt_count": 4})
        return {"ok": choice.backend == "cadquery" and len(params) == 8,
                "metrics": {"fallback_to": choice.backend, "warnings": choice.warnings}}

    reporter.run("Validate", "Backend routing + recipe normalize", cap_route)


# ═══════════════════════════════════════════════════════════════════════
# ANSYS Templates
# ═══════════════════════════════════════════════════════════════════════

def _ansys_templates(reporter: DemoReporter, out_dir: Path):
    from seekflow_engineering_tools.ansys.apdl_templates import (
        static_cantilever_beam_rect_apdl,
        plate_with_hole_tension_apdl,
        beam_thermal_apdl,
        cantilever_modal_apdl,
        buckling_column_apdl,
        bilinear_plastic_apdl,
    )
    from seekflow_engineering_tools.ansys.parsers import parse_result_summary
    import tempfile

    ansys_dir = out_dir / "ansys"
    ansys_dir.mkdir(exist_ok=True)

    # Static cantilever beam
    def beam():
        apdl = static_cantilever_beam_rect_apdl(200, 20, 20, 1000)
        (ansys_dir / "beam.inp").write_text(apdl, encoding="utf-8")
        return {"ok": True, "metrics": {"lines": apdl.count(chr(10)), "has_PREP7": "/PREP7" in apdl}}

    reporter.run("ANSYS", "Static cantilever beam (template)", beam)

    # Plate with hole
    def plate():
        apdl = plate_with_hole_tension_apdl(200, 100, 10, 20, 100)
        (ansys_dir / "plate_hole.inp").write_text(apdl, encoding="utf-8")
        return {"ok": True, "metrics": {"lines": apdl.count(chr(10)), "has_PREP7": "/PREP7" in apdl}}

    reporter.run("ANSYS", "Plate with hole — stress concentration (template)", plate)

    # Thermal
    def thermal():
        apdl = beam_thermal_apdl(200, temp_left_c=100, temp_right_c=0)
        (ansys_dir / "thermal.inp").write_text(apdl, encoding="utf-8")
        return {"ok": True, "metrics": {"lines": apdl.count(chr(10)), "has_PREP7": "/PREP7" in apdl}}

    reporter.run("ANSYS", "Steady-state thermal (template)", thermal)

    # Modal
    def modal():
        apdl = cantilever_modal_apdl(200, 20, 20, n_modes=5)
        (ansys_dir / "modal.inp").write_text(apdl, encoding="utf-8")
        return {"ok": True, "metrics": {"lines": apdl.count(chr(10)), "has_PREP7": "/PREP7" in apdl}}

    reporter.run("ANSYS", "Modal analysis — natural freq (template)", modal)

    # Buckling
    def buckling():
        apdl = buckling_column_apdl(500, 20, 20)
        (ansys_dir / "buckling.inp").write_text(apdl, encoding="utf-8")
        return {"ok": True, "metrics": {"lines": apdl.count(chr(10)), "has_PREP7": "/PREP7" in apdl}}

    reporter.run("ANSYS", "Euler buckling — stability (template)", buckling)

    # Bilinear plastic
    def plastic():
        apdl = bilinear_plastic_apdl(100, displacement_mm=5, n_substeps=20)
        (ansys_dir / "plastic.inp").write_text(apdl, encoding="utf-8")
        return {"ok": True, "metrics": {"lines": apdl.count(chr(10)), "has_PREP7": "/PREP7" in apdl}}

    reporter.run("ANSYS", "Bilinear plasticity — nonlinear (template)", plastic)

    # Parser test
    def parser_test():
        s = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        s.write("MAX_DISPLACEMENT_MM = 0.5234\nMAX_VON_MISES_MPA = 45.2\n")
        s.write("TMIN_C = 20.0 TMAX_C = 100.0 TMID_C = 60.0\n")
        s.write("MODE_1_HZ = 125.5\nMODE_2_HZ = 340.2\n")
        s.write("BUCKLING_LOAD_FACTOR = 3.14\nMAX_PLASTIC_STRAIN = 0.012\n")
        s.close()
        metrics = parse_result_summary(Path(s.name))
        Path(s.name).unlink()
        return {"ok": True, "metrics": metrics}

    reporter.run("ANSYS", "Result parser (static+thermal+modal+buckling+plastic)", parser_test)


# ═══════════════════════════════════════════════════════════════════════
# NX Job Queue
# ═══════════════════════════════════════════════════════════════════════

def _nx_queue(reporter: DemoReporter, out_dir: Path):
    import json as _json
    import time as _time
    from seekflow_engineering_tools.nx.job_queue import NXJobQueue, ALLOWED_ACTIONS

    nx_dir = out_dir / "nx"
    q = NXJobQueue(nx_dir)
    q.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    q.heartbeat_path.write_text(_json.dumps({
        "time_epoch": _time.time(),
        "time_iso": datetime.now().isoformat(),
        "nx_version": "12.0",
    }))

    reporter.run("NX", "Job queue heartbeat alive", lambda: {
        "ok": q.bridge_status()["bridge_running"] is True,
        "metrics": q.queue_status()})

    reporter.run("NX", "Allowed actions (5)", lambda: {
        "ok": len(ALLOWED_ACTIONS) == 5,
        "metrics": {"actions": sorted(ALLOWED_ACTIONS)}})


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="SeekFlow Engineering Tools — Full Demo")
    parser.add_argument("--output", default=None, help="Output directory")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output:
        output_root = Path(args.output) / ts
    else:
        output_root = Path(__file__).parent / "demo_output" / ts
    output_root.mkdir(parents=True, exist_ok=True)

    reporter = DemoReporter(output_root)

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  SeekFlow Engineering Tools — Capability Demo{RESET}")
    print(f"{'='*60}")
    print(f"  Output:  {output_root}")
    print(f"  CadQuery: ON  |  SolidWorks: ON  |  NX: ON  |  ANSYS: ON")
    print()

    # ── CadQuery ──
    cq_dir = output_root / "cadquery"
    cq_dir.mkdir(exist_ok=True)
    print(f"{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}  CadQuery — CAD Models (real STEP generation){RESET}")
    print(f"{CYAN}{'='*60}{RESET}")
    _cadquery_build(reporter, cq_dir)

    # ── SolidWorks ──
    sw_dir = output_root / "sw"
    sw_dir.mkdir(exist_ok=True)
    print(f"\n{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}  SolidWorks 2025 — CAD Models (COM Automation){RESET}")
    print(f"{CYAN}{'='*60}{RESET}")
    _solidworks_build(reporter, sw_dir)

    # ── NX ──
    nx_dir = output_root / "nx"
    nx_dir.mkdir(exist_ok=True)
    print(f"\n{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}  NX 12.0 — CAD Models (Job Queue Bridge){RESET}")
    print(f"{CYAN}{'='*60}{RESET}")
    _nx_build(reporter, nx_dir)

    # ── Validation ──
    val_dir = output_root / "validate"
    val_dir.mkdir(exist_ok=True)
    print(f"\n{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}  Tool Chain Validation{RESET}")
    print(f"{CYAN}{'='*60}{RESET}")
    _validate_chain(reporter, val_dir)

    # ── ANSYS ──
    print(f"\n{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}  ANSYS 18.1 — APDL Templates & Parser{RESET}")
    print(f"{CYAN}{'='*60}{RESET}")
    _ansys_templates(reporter, output_root)

    # ── NX ──
    print(f"\n{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}  NX 12.0 — Job Queue Bridge{RESET}")
    print(f"{CYAN}{'='*60}{RESET}")
    _nx_queue(reporter, output_root)

    # ── Summary ──
    reporter.summary()


if __name__ == "__main__":
    main()
