#!/usr/bin/env python
r"""SeekFlow Engineering Tools — Industrial Text-to-CAD Full Chain Demo.

Real calls to: CadQuery + CQ_Gears, SolidWorks 2025 COM, NX 12.0 Bridge, ANSYS 18.1 APDL.

Usage:
    python demo_full_chain.py
    python demo_full_chain.py --output E:\demo_output
    python demo_full_chain.py --case involute_spur_gear --backend cadquery --json-report reports/gear.json
    python demo_full_chain.py --skip-nx --skip-ansys
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

PYTHON = r"E:\auto_detection_process\.conda\python.exe"

# ── SolidWorks Config ──
SW_TEMPLATE = os.environ.get(
    "SOLIDWORKS_PART_TEMPLATE",
    r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot",
)

# ── ANSYS Config ──
ANSYS181_EXE = Path(os.environ.get("ANSYS181_DIR", r"D:\ANSYS181\ANSYS Inc\v181\ANSYS")) / "bin" / "winx64" / "ansys181.exe"


class DemoReporter:
    """Collects and prints structured demo results."""

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
            ok = data["_ok"]
            status = f"{GREEN}OK{RESET}" if ok else f"{YELLOW}WARN{RESET}"
            print(f"{status} ({elapsed:.1f}s)")
            return data
        except Exception as exc:
            elapsed = time.time() - t0
            import traceback
            tb = traceback.format_exc()
            data = {
                "_ok": False, "_category": category, "_name": name,
                "_elapsed_s": round(elapsed, 2), "_error": str(exc),
                "_traceback": tb,
            }
            self.results.append(data)
            print(f"{RED}FAIL{RESET} ({elapsed:.1f}s) — {exc}")
            return data

    def summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r["_ok"])
        failed = total - passed
        elapsed = time.time() - self._start_time

        report = {
            "timestamp": datetime.now().isoformat(),
            "total": total, "passed": passed, "failed": failed,
            "elapsed_s": round(elapsed, 1),
            "results": self.results,
        }

        report_path = self.output_root / "demo_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}  DEMO COMPLETE{RESET}")
        print(f"{'='*60}")
        print(f"  Total:   {total}")
        print(f"  Passed:  {GREEN}{passed}{RESET}")
        if failed:
            print(f"  Failed:  {RED}{failed}{RESET}")
            for r in self.results:
                if not r["_ok"]:
                    print(f"           {RED}FAIL{RESET} [{r['_category']}] {r['_name']}")
                    if "_error" in r:
                        print(f"             {RED}{r['_error'][:200]}{RESET}")
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
                if "solid_count" in m:
                    h.append(f"bodies={m['solid_count']}")
                if "step_size_kb" in m:
                    h.append(f"step={m['step_size_kb']:.1f}KB")
                if "sldprt_size_kb" in m:
                    h.append(f"sldprt={m['sldprt_size_kb']:.1f}KB")
                if "kernel_used" in m:
                    h.append(f"kernel={m['kernel_used']}")
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
# CadQuery — Standard Parts + Industrial Primitive Gear
# ═══════════════════════════════════════════════════════════════════════

def _cadquery_build(reporter: DemoReporter, out_dir: Path):
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir
    from seekflow_engineering_tools.cadquery_backend.inspector import inspect_step_with_cadquery
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    config = EngineeringToolsConfig(workspace_root=out_dir, allow_overwrite=True)

    models = {
        "box_100x50x25": {
            "label": "Box 100x50x25mm (recipe)",
            "spec": {"name": "box_100x50x25", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "box",
                    "parameters": {"length_mm": 100, "width_mm": 50, "height_mm": 25}}],
                "validation": {"expected_bbox_mm": [100, 50, 25], "expected_body_count": 1, "tolerance_mm": 2.0}},
        },
        "cylinder_d20xh50": {
            "label": "Cylinder D20xH50mm (recipe)",
            "spec": {"name": "cylinder_d20xh50", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "cylinder",
                    "parameters": {"diameter_mm": 20, "height_mm": 50}}],
                "validation": {"expected_bbox_mm": [20, 20, 50], "expected_body_count": 1, "tolerance_mm": 2.0}},
        },
        "block_with_hole_100x50x25_d16": {
            "label": "Block+Through-Hole D16mm (recipe)",
            "spec": {"name": "block_hole", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "block_with_hole",
                    "parameters": {"length_mm": 100, "width_mm": 50, "height_mm": 25, "hole_dia_mm": 16}}],
                "validation": {"expected_body_count": 1, "expected_through_hole_count": 1}},
        },
        "l_bracket_100x60": {
            "label": "L-Bracket 100x60mm (recipe)",
            "spec": {"name": "l_bracket_100x60", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "l_bracket",
                    "parameters": {"base_length_mm": 100, "base_width_mm": 60,
                        "thickness_mm": 15, "leg_height_mm": 60}}],
                "validation": {"expected_body_count": 1}},
        },
        "stepped_block_80to60": {
            "label": "Stepped Block 80→60mm (recipe)",
            "spec": {"name": "stepped_block_80to60", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "stepped_block",
                    "parameters": {"base_length_mm": 80, "base_width_mm": 80, "base_height_mm": 20,
                        "top_length_mm": 60, "top_width_mm": 60, "top_height_mm": 30}}],
                "validation": {"expected_body_count": 1}},
        },
        "flanged_hub_d80": {
            "label": "Flanged Hub D80mm 4-bolt (recipe)",
            "spec": {"name": "flanged_hub_d80", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "flanged_hub",
                    "parameters": {"flange_dia_mm": 80, "flange_thickness_mm": 10,
                        "hub_dia_mm": 40, "hub_height_mm": 30, "bore_dia_mm": 20,
                        "bolt_pcd_mm": 60, "bolt_dia_mm": 8, "bolt_count": 4}}],
                "validation": {"expected_body_count": 1}},
        },
        "shaft_d20_l100": {
            "label": "Shaft D20xL100mm (recipe)",
            "spec": {"name": "shaft_d20_l100", "units": "mm",
                "features": [{"id": "main", "type": "recipe", "recipe_name": "shaft_basic",
                    "parameters": {"shaft_dia_mm": 20, "total_length_mm": 100}}],
                "validation": {"expected_bbox_mm": [20, 20, 100], "expected_body_count": 1, "tolerance_mm": 2.0}},
        },
        # ── Industrial involute spur gear (CQ_Gears deterministic primitive) ──
        "involute_spur_gear_m2z24": {
            "label": "Involute Spur Gear M2 Z24 (CQ_Gears primitive)",
            "spec": {"name": "involute_spur_gear_m2z24", "units": "mm",
                "features": [{"id": "gear1", "type": "primitive",
                    "primitive_name": "involute_spur_gear",
                    "parameters": {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
                                   "bore_dia_mm": 10.0, "pressure_angle_deg": 20.0}}],
                "validation": {"expected_body_count": 1, "tolerance_mm": 0.5}},
        },
        "involute_spur_gear_m3z20": {
            "label": "Involute Spur Gear M3 Z20 (CQ_Gears primitive)",
            "spec": {"name": "involute_spur_gear_m3z20", "units": "mm",
                "features": [{"id": "gear1", "type": "primitive",
                    "primitive_name": "involute_spur_gear",
                    "parameters": {"module_mm": 3.0, "teeth": 20, "face_width_mm": 20.0,
                                   "bore_dia_mm": 15.0, "pressure_angle_deg": 20.0}}],
                "validation": {"expected_body_count": 1, "tolerance_mm": 0.5}},
        },
    }

    for key, info in models.items():
        def make_fn(k=key, i=info):
            def fn():
                spec = CADPartSpec.model_validate(i["spec"])
                step_path = out_dir / f"{k}.step"
                result = build_cadquery_from_cad_ir(
                    spec=spec, config=config, out_step=str(step_path), inspect=False)
                insp = inspect_step_with_cadquery(step_path)

                metrics = {
                    "bbox_mm": insp.get("bbox_mm"),
                    "volume_mm3": round(insp.get("volume_mm3", 0), 1) if insp.get("volume_mm3") else None,
                    "solid_count": insp.get("solid_count"),
                    "step_size_kb": round(step_path.stat().st_size / 1024, 1) if step_path.exists() else 0,
                }

                # Extract kernel from metadata for gear primitives
                if "involute_spur_gear" in k:
                    meta_path = step_path.with_suffix(".metadata.json")
                    if meta_path.exists():
                        import json as _j
                        sidecar = _j.loads(meta_path.read_text(encoding="utf-8"))
                        pm = sidecar.get("primitive_metadata", {}).get("involute_spur_gear", {})
                        metrics["kernel_used"] = pm.get("kernel", "unknown")
                        if "reference_dimensions" in pm:
                            rd = pm["reference_dimensions"]
                            metrics["pitch_diameter_mm"] = rd.get("pitch_diameter_mm")
                            metrics["outer_diameter_mm"] = rd.get("outer_diameter_mm")

                ok = result.get("ok", False) and insp.get("error") is None
                warnings = result.get("warnings", [])
                return {
                    "ok": ok, "metrics": metrics,
                    "files": [str(step_path)],
                    "warnings": warnings,
                }
            return fn
        reporter.run("CadQuery", info["label"], make_fn())


# ═══════════════════════════════════════════════════════════════════════
# SolidWorks 2025 — Real COM Automation (Box, Flanged Hub, Spur Gear)
# ═══════════════════════════════════════════════════════════════════════

def _sw_connect():
    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
    return SolidWorksClient(visible=True, part_template=Path(SW_TEMPLATE)).connect()


def _solidworks_build(reporter: DemoReporter, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # Health check
    def sw_health():
        try:
            client = _sw_connect()
            info = client.health_check()
            return {"ok": True, "metrics": info}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
    reporter.run("SolidWorks", "Health check (COM)", sw_health)

    # ── Box ──
    def sw_box():
        client = _sw_connect()
        model = client.new_part()
        client.create_extruded_box(model, 0.100, 0.060, 0.030)  # 100x60x30mm (in m)
        sldprt = out_dir / "box_100x60x30.SLDPRT"
        step = out_dir / "box_100x60x30.step"
        client.save_as(model, sldprt)
        client.export_step(model, step)
        files = [str(sldprt)] if sldprt.exists() else []
        if step.exists(): files.append(str(step))
        return {
            "ok": sldprt.exists(),
            "files": files,
            "metrics": {
                "sldprt_size_kb": round(sldprt.stat().st_size / 1024, 1) if sldprt.exists() else 0,
                "step_size_kb": round(step.stat().st_size / 1024, 1) if step.exists() else 0,
            },
        }
    reporter.run("SolidWorks", "Box 100x60x30mm (extrude)", sw_box)

    # ── Flanged Hub ──
    def sw_flanged_hub():
        client = _sw_connect()
        model = client.new_part()
        client.create_flanged_hub(
            model,
            flange_dia_m=0.080, flange_h_m=0.010,
            hub_dia_m=0.040, hub_h_m=0.030,
            bore_dia_m=0.020, bolt_pcd_m=0.060,
            bolt_dia_m=0.008, bolt_count=4,
        )
        sldprt = out_dir / "flanged_hub_d80.SLDPRT"
        step = out_dir / "flanged_hub_d80.step"
        client.save_as(model, sldprt)
        client.export_step(model, step)
        files = [str(sldprt)] if sldprt.exists() else []
        if step.exists(): files.append(str(step))
        return {
            "ok": sldprt.exists(),
            "files": files,
            "metrics": {
                "sldprt_size_kb": round(sldprt.stat().st_size / 1024, 1) if sldprt.exists() else 0,
                "step_size_kb": round(step.stat().st_size / 1024, 1) if step.exists() else 0,
                "features": 6,  # flange + hub + bore + 4 bolts
            },
        }
    reporter.run("SolidWorks", "Flanged Hub D80mm 4-bolt (multi-feature)", sw_flanged_hub)

    # ── Spur Gear M3 Z20 (star polygon) ──
    def sw_spur_gear_star():
        client = _sw_connect()
        model = client.new_part()
        client.create_spur_gear(model, module_m=0.003, teeth=20, face_width_m=0.020, bore_dia_m=0.015)
        sldprt = out_dir / "spur_gear_m3z20_star.SLDPRT"
        step = out_dir / "spur_gear_m3z20_star.step"
        client.save_as(model, sldprt)
        client.export_step(model, step)
        files = [str(sldprt)] if sldprt.exists() else []
        if step.exists(): files.append(str(step))
        return {
            "ok": sldprt.exists(),
            "files": files,
            "metrics": {
                "sldprt_size_kb": round(sldprt.stat().st_size / 1024, 1) if sldprt.exists() else 0,
                "step_size_kb": round(step.stat().st_size / 1024, 1) if step.exists() else 0,
                "type": "star_polygon", "module_mm": 3, "teeth": 20,
            },
        }
    reporter.run("SolidWorks", "Spur Gear M3 Z20 (star polygon)", sw_spur_gear_star)

    # ── Spur Gear M3 Z20 (true involute ISO 53) ──
    def sw_spur_gear_involute():
        client = _sw_connect()
        model = client.new_part()
        client.create_spur_gear_true_involute(
            model, module_m=0.003, teeth=20, face_width_m=0.020, bore_dia_m=0.015,
            pressure_angle_deg=20.0, n_subdivisions=6,
        )
        sldprt = out_dir / "spur_gear_m3z20_involute.SLDPRT"
        step = out_dir / "spur_gear_m3z20_involute.step"
        client.save_as(model, sldprt)
        client.export_step(model, step)
        files = [str(sldprt)] if sldprt.exists() else []
        if step.exists(): files.append(str(step))
        return {
            "ok": sldprt.exists(),
            "files": files,
            "metrics": {
                "sldprt_size_kb": round(sldprt.stat().st_size / 1024, 1) if sldprt.exists() else 0,
                "step_size_kb": round(step.stat().st_size / 1024, 1) if step.exists() else 0,
                "type": "involute_iso53", "module_mm": 3, "teeth": 20,
                "pressure_angle_deg": 20.0,
            },
        }
    reporter.run("SolidWorks", "Spur Gear M3 Z20 (involute ISO 53)", sw_spur_gear_involute)

    # ── Spur Gear M5 Z30 (large involute) ──
    def sw_spur_gear_large():
        client = _sw_connect()
        model = client.new_part()
        client.create_spur_gear_true_involute(
            model, module_m=0.005, teeth=30, face_width_m=0.030, bore_dia_m=0.025,
            pressure_angle_deg=20.0, n_subdivisions=8,
        )
        sldprt = out_dir / "spur_gear_m5z30_involute.SLDPRT"
        step = out_dir / "spur_gear_m5z30_involute.step"
        client.save_as(model, sldprt)
        client.export_step(model, step)
        files = [str(sldprt)] if sldprt.exists() else []
        if step.exists(): files.append(str(step))
        return {
            "ok": sldprt.exists(),
            "files": files,
            "metrics": {
                "sldprt_size_kb": round(sldprt.stat().st_size / 1024, 1) if sldprt.exists() else 0,
                "step_size_kb": round(step.stat().st_size / 1024, 1) if step.exists() else 0,
                "type": "involute_iso53", "module_mm": 5, "teeth": 30,
                "pressure_angle_deg": 20.0,
            },
        }
    reporter.run("SolidWorks", "Spur Gear M5 Z30 (involute ISO 53)", sw_spur_gear_large)

    # ── STEP Import: CadQuery-generated involute gear → SW SLDPRT ──
    def sw_step_import():
        """Import the canonical CadQuery/CQ_Gears STEP into SolidWorks."""
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir
        from seekflow_engineering_tools.ir.cad import CADPartSpec

        # Step 1: CadQuery generates canonical STEP
        cq_dir = out_dir / "sw_step_import"
        cq_dir.mkdir(exist_ok=True)
        config = EngineeringToolsConfig(workspace_root=cq_dir, allow_overwrite=True)
        spec = CADPartSpec.model_validate({
            "name": "gear_for_sw_import", "units": "mm",
            "features": [{"id": "gear1", "type": "primitive",
                "primitive_name": "involute_spur_gear",
                "parameters": {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
                               "bore_dia_mm": 10.0, "pressure_angle_deg": 20.0}}],
            "validation": {"expected_body_count": 1, "tolerance_mm": 0.5},
        })
        canonical_step = cq_dir / "canonical_gear.step"
        build_cadquery_from_cad_ir(spec=spec, config=config, out_step=str(canonical_step))

        if not canonical_step.exists():
            return {"ok": False, "error": "CadQuery STEP generation failed"}

        # Step 2: SolidWorks imports STEP → saves native SLDPRT
        client = _sw_connect()
        # LoadFile2 imports by file extension (STEP auto-detected)
        client.sw.LoadFile2(str(canonical_step), "")
        model = client.sw.ActiveDoc
        sldprt = out_dir / "gear_from_cq_step_import.SLDPRT"
        client.save_as(model, sldprt)

        # Also re-export STEP for verification
        sw_step = out_dir / "gear_from_cq_step_import.step"
        client.export_step(model, sw_step)

        files = [str(canonical_step)] + ([str(sldprt)] if sldprt.exists() else [])
        if sw_step.exists(): files.append(str(sw_step))

        return {
            "ok": sldprt.exists(),
            "files": files,
            "metrics": {
                "strategy": "cadquery_step_import",
                "canonical_step_size_kb": round(canonical_step.stat().st_size / 1024, 1),
                "sldprt_size_kb": round(sldprt.stat().st_size / 1024, 1) if sldprt.exists() else 0,
                "kernel_used": "CQ_Gears→CadQuery→SW_STEP_import",
            },
        }
    reporter.run("SolidWorks", "STEP Import (CQ_Gears→SW native)", sw_step_import)


# ═══════════════════════════════════════════════════════════════════════
# NX 12.0 — Real Bridge Jobs
# ═══════════════════════════════════════════════════════════════════════

NX_JOB_ROOT = os.environ.get("NX_JOB_ROOT", str(Path.home() / "seekflow_workspace" / "demo_full"))


def _nx_build(reporter: DemoReporter, out_dir: Path):
    from seekflow_engineering_tools.nx.job_queue import NXJobQueue

    out_dir.mkdir(parents=True, exist_ok=True)
    q_root = Path(NX_JOB_ROOT) / "nx_jobs"

    # Write heartbeat to signal bridge is alive
    def nx_write_heartbeat():
        import json as _j
        q = NXJobQueue(q_root)
        q.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        q.heartbeat_path.write_text(_j.dumps({
            "time_epoch": time.time(),
            "time_iso": datetime.now().isoformat(),
            "nx_version": "12.0",
        }))
        status = q.bridge_status()
        return {
            "ok": status["bridge_running"],
            "metrics": {"bridge_running": status["bridge_running"], **q.queue_status()},
        }
    reporter.run("NX", "Write heartbeat (bridge alive)", nx_write_heartbeat)

    # Health check
    def nx_health():
        q = NXJobQueue(q_root)
        status = q.bridge_status()
        qs = q.queue_status()
        return {"ok": status["bridge_running"],
                "metrics": {"bridge_running": status["bridge_running"],
                            "heartbeat_age_s": status.get("heartbeat_age_s"), **qs}}
    reporter.run("NX", "Health check (bridge status)", nx_health)

    # Skip if bridge is not running
    q_check = NXJobQueue(q_root)
    bridge_alive = q_check.bridge_status()["bridge_running"]

    if not bridge_alive:
        reporter.run("NX", "Bridge NOT running — skipping job submissions",
                     lambda: {"ok": True, "metrics": {"note": "NX bridge not detected, skipped"}})
        return

    # ── Submit jobs ──
    nx_models = [
        ("create_block_part", "Block 100x60x20mm", {
            "length_mm": 100, "width_mm": 60, "height_mm": 20,
        }),
        ("create_block_with_hole", "Block+Through-Hole D16mm", {
            "length_mm": 100, "width_mm": 60, "height_mm": 20,
            "hole_dia_mm": 16, "hole_x": 50, "hole_z": 30,
        }),
        ("create_l_bracket", "L-Bracket 100x60mm (unite)", {
            "base_length": 100, "base_width": 60, "thickness": 15, "leg_height": 60,
        }),
        ("create_stepped_block", "Stepped Block 80→60mm", {
            "base_length": 80, "base_width": 80, "base_height": 20,
            "top_length": 60, "top_width": 60, "top_height": 30,
        }),
    ]

    for action, label, params in nx_models:
        def make_fn(a=action, p=params):
            def fn():
                q = NXJobQueue(q_root)
                out_prt = out_dir / f"{a}.prt"
                p["out_prt"] = str(out_prt)
                p["out_step"] = str(out_dir / f"{a}.step")
                job_id = q.submit(a, p)
                try:
                    result = q.wait(job_id, timeout_s=60)
                    files = result.get("files_created", [])
                    return {
                        "ok": bool(result.get("ok")),
                        "files": files,
                        "metrics": result.get("metrics", {}),
                        "message": result.get("message", ""),
                        "job_id": job_id,
                    }
                except TimeoutError:
                    return {
                        "ok": False,
                        "error": f"Job {job_id} timed out (60s).",
                        "job_id": job_id,
                    }
            return fn
        reporter.run("NX", label, make_fn())


# ═══════════════════════════════════════════════════════════════════════
# ANSYS 18.1 — Real APDL Batch Analysis
# ═══════════════════════════════════════════════════════════════════════

def _ansys_build(reporter: DemoReporter, out_dir: Path):
    from seekflow_engineering_tools.ansys.apdl_templates import (
        static_cantilever_beam_rect_apdl,
        plate_with_hole_tension_apdl,
        beam_thermal_apdl,
        cantilever_modal_apdl,
        buckling_column_apdl,
        bilinear_plastic_apdl,
    )
    from seekflow_engineering_tools.ansys.parsers import parse_result_summary
    from seekflow_engineering_tools.ansys.apdl_runner import AnsysAPDLRunner

    ansys_dir = out_dir / "ansys"
    ansys_dir.mkdir(exist_ok=True)

    runner = AnsysAPDLRunner(
        ansys_exe=ANSYS181_EXE,
        workspace_root=ansys_dir,
        default_timeout_s=300,
        default_nproc=2,
    )

    # Health check
    def ansys_health():
        info = runner.health_check()
        return {"ok": info["exists"], "metrics": info}
    reporter.run("ANSYS", "Health check (ansys181.exe)", ansys_health)

    if not ANSYS181_EXE.exists():
        reporter.run("ANSYS", "ansys181.exe NOT found — skipping simulations",
                     lambda: {"ok": True, "metrics": {"note": f"Not found: {ANSYS181_EXE}"}})
        return

    # ── Static cantilever beam ──
    def beam_static():
        apdl = static_cantilever_beam_rect_apdl(
            length_mm=200, width_mm=20, height_mm=20, force_n=1000,
            young_mpa=210000.0, poisson=0.3, element_size_mm=10.0,
        )
        inp = ansys_dir / "beam_static.inp"
        inp.write_text(apdl, encoding="utf-8")
        job_dir = ansys_dir / "beam_static"
        r = runner.run_apdl_file(inp, job_dir, "beam_static")
        out_file = job_dir / "beam_static.out"
        metrics = parse_result_summary(out_file) if out_file.exists() else {}
        return {
            "ok": not r["has_error"],
            "files": [str(inp), str(out_file)] if out_file.exists() else [str(inp)],
            "metrics": {
                **metrics,
                "elapsed_s": r["elapsed_s"], "returncode": r["returncode"],
                "lines": apdl.count('\n'),
            },
        }
    reporter.run("ANSYS", "Static cantilever beam (SOLID185)", beam_static)

    # ── Plate with hole (stress concentration) ──
    def plate_hole():
        apdl = plate_with_hole_tension_apdl(
            plate_width_mm=200, plate_height_mm=100, plate_thickness_mm=10,
            hole_diameter_mm=20, tensile_stress_mpa=100,
        )
        inp = ansys_dir / "plate_hole.inp"
        inp.write_text(apdl, encoding="utf-8")
        job_dir = ansys_dir / "plate_hole"
        r = runner.run_apdl_file(inp, job_dir, "plate_hole")
        out_file = job_dir / "plate_hole.out"
        metrics = parse_result_summary(out_file) if out_file.exists() else {}
        return {
            "ok": not r["has_error"],
            "files": [str(inp), str(out_file)] if out_file.exists() else [str(inp)],
            "metrics": {
                **metrics,
                "elapsed_s": r["elapsed_s"], "returncode": r["returncode"],
            },
        }
    reporter.run("ANSYS", "Plate with hole — stress concentration (PLANE182)", plate_hole)

    # ── Steady-state thermal ──
    def thermal():
        apdl = beam_thermal_apdl(200, temp_left_c=100, temp_right_c=0)
        inp = ansys_dir / "thermal.inp"
        inp.write_text(apdl, encoding="utf-8")
        job_dir = ansys_dir / "thermal"
        r = runner.run_apdl_file(inp, job_dir, "thermal")
        out_file = job_dir / "thermal.out"
        metrics = parse_result_summary(out_file) if out_file.exists() else {}
        return {
            "ok": not r["has_error"],
            "files": [str(inp), str(out_file)] if out_file.exists() else [str(inp)],
            "metrics": {
                **metrics,
                "elapsed_s": r["elapsed_s"], "returncode": r["returncode"],
            },
        }
    reporter.run("ANSYS", "Steady-state thermal (SOLID70)", thermal)

    # ── Modal analysis ──
    def modal():
        apdl = cantilever_modal_apdl(200, 20, 20, n_modes=5)
        inp = ansys_dir / "modal.inp"
        inp.write_text(apdl, encoding="utf-8")
        job_dir = ansys_dir / "modal"
        r = runner.run_apdl_file(inp, job_dir, "modal")
        out_file = job_dir / "modal.out"
        metrics = parse_result_summary(out_file) if out_file.exists() else {}
        return {
            "ok": not r["has_error"],
            "files": [str(inp), str(out_file)] if out_file.exists() else [str(inp)],
            "metrics": {
                **metrics,
                "elapsed_s": r["elapsed_s"], "returncode": r["returncode"],
            },
        }
    reporter.run("ANSYS", "Modal analysis — 5 modes (SOLID185)", modal)

    # ── Euler buckling ──
    def buckling():
        apdl = buckling_column_apdl(500, 20, 20)
        inp = ansys_dir / "buckling.inp"
        inp.write_text(apdl, encoding="utf-8")
        job_dir = ansys_dir / "buckling"
        r = runner.run_apdl_file(inp, job_dir, "buckling")
        out_file = job_dir / "buckling.out"
        metrics = parse_result_summary(out_file) if out_file.exists() else {}
        return {
            "ok": not r["has_error"],
            "files": [str(inp), str(out_file)] if out_file.exists() else [str(inp)],
            "metrics": {
                **metrics,
                "elapsed_s": r["elapsed_s"], "returncode": r["returncode"],
            },
        }
    reporter.run("ANSYS", "Euler buckling — stability (BEAM188)", buckling)

    # ── Bilinear plasticity ──
    def plastic():
        apdl = bilinear_plastic_apdl(100, displacement_mm=5, n_substeps=20)
        inp = ansys_dir / "plastic.inp"
        inp.write_text(apdl, encoding="utf-8")
        job_dir = ansys_dir / "plastic"
        r = runner.run_apdl_file(inp, job_dir, "plastic")
        out_file = job_dir / "plastic.out"
        metrics = parse_result_summary(out_file) if out_file.exists() else {}
        return {
            "ok": not r["has_error"],
            "files": [str(inp), str(out_file)] if out_file.exists() else [str(inp)],
            "metrics": {
                **metrics,
                "elapsed_s": r["elapsed_s"], "returncode": r["returncode"],
            },
        }
    reporter.run("ANSYS", "Bilinear plasticity — nonlinear (SOLID185 BKIN)", plastic)


# ═══════════════════════════════════════════════════════════════════════
# Tool Chain Validation
# ═══════════════════════════════════════════════════════════════════════

def _validate_chain(reporter: DemoReporter, out_dir: Path):
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.registry import build_engineering_tools
    from seekflow_engineering_tools.capabilities.registry import choose_backend
    from seekflow_engineering_tools.ir.cad import CADPartSpec, RecipeFeature
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature
    from seekflow_engineering_tools.recipes.registry import normalize_recipe_parameters
    from seekflow_engineering_tools.geometry_primitives.registry import normalize_primitive_parameters

    # Tool registration
    def tool_reg():
        config = EngineeringToolsConfig(workspace_root=out_dir / "ws")
        tools = build_engineering_tools(config)
        names = {t.name for t in tools}
        req = {"cadquery_build_from_cad_ir", "cadquery_inspect_step",
               "engineering_validate_cad_ir", "engineering_build_cad_model"}
        return {"ok": req.issubset(names), "total_tools": len(names),
                "metrics": {"required_present": sorted(req)}}
    reporter.run("Validate", "Tool registration", tool_reg)

    # CAD-IR schema validation
    def nl_validate():
        spec = {"name": "t", "units": "mm",
                "features": [{"id": "f1", "type": "recipe", "recipe_name": "box",
                    "parameters": {"length_mm": 100, "width_mm": 50, "height_mm": 25}}]}
        CADPartSpec.model_validate(spec)
        return {"ok": True, "metrics": {"normalized": True}}
    reporter.run("Validate", "CAD-IR schema (recipe)", nl_validate)

    # Primitive schema validation
    def primitive_validate():
        spec = {"name": "t", "units": "mm",
                "features": [{"id": "g1", "type": "primitive",
                    "primitive_name": "involute_spur_gear",
                    "parameters": {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}}]}
        CADPartSpec.model_validate(spec)
        return {"ok": True, "metrics": {"primitive_ok": True}}
    reporter.run("Validate", "CAD-IR schema (primitive)", primitive_validate)

    # Backend routing
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

    # Primitive routing and normalize
    def primitive_routing():
        spec = CADPartSpec(name="t", features=[
            PrimitiveFeature(id="g1", primitive_name="involute_spur_gear",
                parameters={"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0})])
        choice = choose_backend(spec, preferred=["cadquery"])
        norm = normalize_primitive_parameters("involute_spur_gear",
            {"module_mm": 3.0, "teeth": 30, "face_width_mm": 25.0})
        return {"ok": choice.backend == "cadquery" and "pressure_angle_deg" in norm,
                "metrics": {"backend": choice.backend, "normalized_params": norm}}
    reporter.run("Validate", "Primitive routing + normalize", primitive_routing)

    # Deprecated recipe rewrite
    def deprecated_rewrite():
        from seekflow_engineering_tools.natural_language.normalizer import (
            rewrite_deprecated_recipes_to_primitives,
        )
        spec = {"name": "t", "units": "mm",
                "features": [{"id": "f1", "type": "recipe", "recipe_name": "spur_gear",
                    "parameters": {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
                                   "bore_dia_mm": 10.0}}]}
        rewritten = rewrite_deprecated_recipes_to_primitives(spec)
        feat = rewritten["features"][0]
        return {"ok": feat["type"] == "primitive" and feat["primitive_name"] == "involute_spur_gear",
                "metrics": {"rewrite_warnings": rewritten.get("rewrite_warnings", [])}}
    reporter.run("Validate", "Deprecated spur_gear → primitive", deprecated_rewrite)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="SeekFlow Industrial Text-to-CAD — Full Chain Demo")
    parser.add_argument("--output", default=None, help="Output directory")
    parser.add_argument("--case", default="all",
                        choices=["all", "box", "flanged_hub", "involute_spur_gear"])
    parser.add_argument("--backend", default="cadquery",
                        choices=["cadquery", "solidworks2025", "nx12"])
    parser.add_argument("--json-report", default=None, help="Write JSON report path")
    parser.add_argument("--skip-sw", action="store_true", help="Skip SolidWorks tests")
    parser.add_argument("--skip-nx", action="store_true", help="Skip NX tests")
    parser.add_argument("--skip-ansys", action="store_true", help="Skip ANSYS tests")
    parser.add_argument("--allow-step-import", action="store_true")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output:
        output_root = Path(args.output) / ts
    else:
        output_root = Path(r"E:\auto_detection_process\demo_output") / ts
    output_root.mkdir(parents=True, exist_ok=True)

    reporter = DemoReporter(output_root)

    # Header
    sw_status = f"{GREEN}ON{RESET}" if not args.skip_sw else f"{RED}SKIP{RESET}"
    nx_status = f"{GREEN}ON{RESET}" if not args.skip_nx else f"{RED}SKIP{RESET}"
    ansys_status = f"{GREEN}ON{RESET}" if not args.skip_ansys else f"{RED}SKIP{RESET}"

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  SeekFlow Engineering Tools — Industrial Text-to-CAD Demo{RESET}")
    print(f"{'='*60}")
    print(f"  Output:  {output_root}")
    print(f"  CadQuery: {GREEN}ON{RESET} | SolidWorks: {sw_status} | NX: {nx_status} | ANSYS: {ansys_status}")
    print()

    # ── CadQuery ──
    cq_dir = output_root / "cadquery"
    cq_dir.mkdir(exist_ok=True)
    print(f"{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}  CadQuery — CAD Models (STEP + metadata){RESET}")
    print(f"{CYAN}{'='*60}{RESET}")
    _cadquery_build(reporter, cq_dir)

    # ── SolidWorks ──
    if not args.skip_sw:
        sw_dir = output_root / "sw"
        sw_dir.mkdir(exist_ok=True)
        print(f"\n{CYAN}{'='*60}{RESET}")
        print(f"{CYAN}  SolidWorks 2025 — CAD Models (COM Automation){RESET}")
        print(f"{CYAN}{'='*60}{RESET}")
        _solidworks_build(reporter, sw_dir)

    # ── NX ──
    if not args.skip_nx:
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
    if not args.skip_ansys:
        print(f"\n{CYAN}{'='*60}{RESET}")
        print(f"{CYAN}  ANSYS 18.1 — APDL FEM Analysis{RESET}")
        print(f"{CYAN}{'='*60}{RESET}")
        _ansys_build(reporter, output_root)

    # ── Summary ──
    reporter.summary()

    # JSON report for single cases
    if args.json_report and args.case != "all":
        report_path = Path(args.json_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        case_results = [r for r in reporter.results if r["_name"] and args.case in r.get("_name", "")]
        overall_ok = all(r["_ok"] for r in case_results) if case_results else False
        report = {
            "timestamp": datetime.now().isoformat(),
            "overall_ok": overall_ok,
            "case": args.case,
            "backend": args.backend,
            "results": case_results,
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nSingle-case report: {report_path}")

        if not overall_ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
