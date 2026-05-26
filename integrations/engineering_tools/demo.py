#!/usr/bin/env python
r"""SeekFlow Engineering Tools — Full Capability Demo.

Runs every verified model and simulation across SolidWorks 2025,
NX 12.0, and ANSYS 18.1.  All outputs land in a timestamped folder
under ENGINEERING_WORKSPACE.

Usage:
    python demo.py                          # run everything
    python demo.py --ansys-only             # only ANSYS simulations
    python demo.py --cad-only               # only SolidWorks + NX
    python demo.py --output D:\results      # custom output folder
    python demo.py --skip-solidworks        # skip SolidWorks tests
    python demo.py --skip-nx                # skip NX tests
    python demo.py --skip-ansys             # skip ANSYS tests
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


class DemoReporter:
    """Collects and prints structured demo results."""

    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.results: list[dict] = []
        self._start_time = time.time()

    def run(self, category: str, name: str, fn):
        """Execute *fn()*, record result, print status."""
        tag = f"[{category}] {name}"
        sys.stdout.write(f"  {tag:<60s} ... ")
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
        print(f"  Failed:  {RED}{failed}{RESET}" if failed else f"  Failed:  0")
        print(f"  Time:    {elapsed:.1f}s")
        print(f"  Output:  {self.output_root}")
        print(f"  Report:  {report_path}")
        print(f"{'='*60}\n")


# ═══════════════════════════════════════════════════════════════════════
# ANSYS tests
# ═══════════════════════════════════════════════════════════════════════


def ansys_runner():
    from seekflow_engineering_tools.ansys.apdl_runner import AnsysAPDLRunner
    ansys_exe = Path(os.environ.get("ANSYS181_EXE",
        r"D:\ANSYS181\ANSYS Inc\v181\ANSYS\bin\winx64\ansys181.exe"))
    return AnsysAPDLRunner(ansys_exe, Path("."), default_timeout_s=300)


def _run_ansys(job_dir: Path, apdl: str, jobname: str) -> dict:
    from seekflow_engineering_tools.ansys.parsers import parse_result_summary
    job_dir.mkdir(parents=True, exist_ok=True)
    inp = job_dir / f"{jobname}.inp"
    inp.write_text(apdl, encoding="utf-8")
    runner = ansys_runner()
    runner.workspace_root = job_dir.parent
    raw = runner.run_apdl_file(inp, job_dir, jobname, timeout_s=300)
    summary = job_dir / "result_summary.txt"
    metrics = parse_result_summary(summary) if summary.exists() else {}
    return {
        "ok": not raw["has_error"],
        "returncode": raw["returncode"],
        "elapsed_s": raw["elapsed_s"],
        "metrics": metrics,
        "output_file": raw["output_file"],
    }


def ansys_static_beam(out_dir: Path) -> dict:
    from seekflow_engineering_tools.ansys.apdl_templates import static_cantilever_beam_rect_apdl
    apdl = static_cantilever_beam_rect_apdl(200, 20, 20, 1000)
    return _run_ansys(out_dir / "ansys_static_beam", apdl, "beam")


def ansys_plate_hole(out_dir: Path) -> dict:
    from seekflow_engineering_tools.ansys.apdl_templates import plate_with_hole_tension_apdl
    apdl = plate_with_hole_tension_apdl(200, 100, 10, 20, 100)
    return _run_ansys(out_dir / "ansys_plate_hole", apdl, "plate")


def ansys_thermal(out_dir: Path) -> dict:
    from seekflow_engineering_tools.ansys.apdl_templates import beam_thermal_apdl
    apdl = beam_thermal_apdl(200, temp_left_c=100, temp_right_c=0)
    return _run_ansys(out_dir / "ansys_thermal", apdl, "thermal")


def ansys_modal(out_dir: Path) -> dict:
    from seekflow_engineering_tools.ansys.apdl_templates import cantilever_modal_apdl
    apdl = cantilever_modal_apdl(200, 20, 20, n_modes=5)
    return _run_ansys(out_dir / "ansys_modal", apdl, "modal")


def ansys_buckling(out_dir: Path) -> dict:
    from seekflow_engineering_tools.ansys.apdl_templates import buckling_column_apdl
    apdl = buckling_column_apdl(500, 20, 20, n_modes=3)
    return _run_ansys(out_dir / "ansys_buckling", apdl, "buckle")


def ansys_plastic(out_dir: Path) -> dict:
    from seekflow_engineering_tools.ansys.apdl_templates import bilinear_plastic_apdl
    apdl = bilinear_plastic_apdl(100, displacement_mm=5, n_substeps=20)
    return _run_ansys(out_dir / "ansys_plastic", apdl, "plastic")


# ═══════════════════════════════════════════════════════════════════════
# SolidWorks tests
# ═══════════════════════════════════════════════════════════════════════

SW_TEMPLATE = os.environ.get(
    "SOLIDWORKS_PART_TEMPLATE",
    r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot",
)


def _sw_connect():
    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
    return SolidWorksClient(visible=True, part_template=Path(SW_TEMPLATE)).connect()


def sw_simple_box(out_dir: Path) -> dict:
    client = _sw_connect()
    model = client.new_part()
    client.create_extruded_box(model, 0.100, 0.060, 0.030)
    sldprt = out_dir / "sw_box.sldprt"
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = client.save_as(model, sldprt)
    return {"ok": ok, "files": [str(sldprt)], "size": sldprt.stat().st_size if ok else 0}


def sw_gear_star(out_dir: Path) -> dict:
    """Spur gear (star polygon) — simplified variant."""
    client = _sw_connect()
    model = client.new_part()
    client.create_spur_gear_star_demo(model, module_m=0.003, teeth=20, face_width_m=0.020, bore_dia_m=0.015)
    out_dir.mkdir(parents=True, exist_ok=True)
    sldprt = out_dir / "sw_gear_star.sldprt"
    step = out_dir / "sw_gear_star.step"
    ok = client.save_as(model, sldprt)
    client.export_step(model, step)
    return {"ok": ok, "files": [str(sldprt), str(step)],
            "size_sldprt": sldprt.stat().st_size if ok else 0,
            "size_step": step.stat().st_size if step.exists() else 0}


def sw_gear_involute(out_dir: Path) -> dict:
    """Spur gear (true involute profile) — 20 teeth, 20pts/flank."""
    client = _sw_connect()
    model = client.new_part()
    client.create_spur_gear_involute(model, module_m=0.003, teeth=20, face_width_m=0.020, bore_dia_m=0.015)
    out_dir.mkdir(parents=True, exist_ok=True)
    sldprt = out_dir / "sw_gear_involute.sldprt"
    step = out_dir / "sw_gear_involute.step"
    ok = client.save_as(model, sldprt)
    client.export_step(model, step)
    return {"ok": ok, "files": [str(sldprt), str(step)],
            "size_sldprt": sldprt.stat().st_size if ok else 0,
            "size_step": step.stat().st_size if step.exists() else 0}


def sw_flanged_hub(out_dir: Path) -> dict:
    """Flanged hub: flange + boss + bore + 4 bolt holes."""
    client = _sw_connect()
    model = client.new_part()
    client.create_flanged_hub(model,
        flange_dia_m=0.080, flange_h_m=0.010,
        hub_dia_m=0.040, hub_h_m=0.030,
        bore_dia_m=0.020, bolt_pcd_m=0.060,
        bolt_dia_m=0.008, bolt_count=4)
    out_dir.mkdir(parents=True, exist_ok=True)
    sldprt = out_dir / "sw_flanged_hub.sldprt"
    step = out_dir / "sw_flanged_hub.step"
    ok = client.save_as(model, sldprt)
    client.export_step(model, step)
    return {"ok": ok, "files": [str(sldprt), str(step)],
            "size_sldprt": sldprt.stat().st_size if ok else 0,
            "size_step": step.stat().st_size if step.exists() else 0}


# ═══════════════════════════════════════════════════════════════════════
# NX tests
# ═══════════════════════════════════════════════════════════════════════

NX_RUNNER = os.environ.get(
    "NX_JOURNAL_RUNNER",
    r"D:\nx\NXBIN\run_journal.exe",
)


def _nx_job_dir():
    return Path(os.environ.get("NX_JOB_ROOT", str(Path.home() / "seekflow_workspace/nx_jobs")))


def _run_nx(action: str, params: dict, timeout_s: int = 120) -> dict:
    from seekflow_engineering_tools.nx.job_queue import NXJobQueue
    q = NXJobQueue(_nx_job_dir())
    job_id = q.submit(action, params)
    return q.wait(job_id, timeout_s=timeout_s)


def nx_simple_block(out_dir: Path) -> dict:
    out = out_dir / "nx_block.prt"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = _run_nx("create_block_part", {
        "length_mm": 100, "width_mm": 60, "height_mm": 20,
        "out_prt": str(out),
    })
    return {"ok": result.get("ok", False),
            "files": [str(out)],
            "size": out.stat().st_size if out.exists() else 0}


def nx_block_with_hole(out_dir: Path) -> dict:
    out = out_dir / "nx_hole.prt"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = _run_nx("create_block_with_hole", {
        "length_mm": 100, "width_mm": 60, "height_mm": 20,
        "hole_dia_mm": 16, "hole_x": 50, "hole_z": 30,
        "out_prt": str(out),
    })
    return {"ok": result.get("ok", False),
            "files": [str(out)],
            "size": out.stat().st_size if out.exists() else 0}


def nx_l_bracket(out_dir: Path) -> dict:
    """L-bracket: two perpendicular blocks united."""
    out = out_dir / "nx_l_bracket.prt"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = _run_nx("create_l_bracket", {
        "base_length": 100, "base_width": 60, "thickness": 15,
        "leg_height": 60, "out_prt": str(out),
    })
    return {"ok": result.get("ok", False),
            "files": [str(out)],
            "size": out.stat().st_size if out.exists() else 0}


def nx_stepped_block(out_dir: Path) -> dict:
    """Stepped block: base + top united."""
    out = out_dir / "nx_stepped_block.prt"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = _run_nx("create_stepped_block", {
        "base_length": 80, "base_width": 80, "base_height": 20,
        "top_length": 60, "top_width": 60, "top_height": 30,
        "out_prt": str(out),
    })
    return {"ok": result.get("ok", False),
            "files": [str(out)],
            "size": out.stat().st_size if out.exists() else 0}


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="SeekFlow Engineering Tools — Full Demo")
    parser.add_argument("--output", default=None,
                        help="Output directory (default: WORKSPACE/demo_YYYYMMDD_HHMMSS)")
    parser.add_argument("--ansys-only", action="store_true")
    parser.add_argument("--cad-only", action="store_true")
    parser.add_argument("--skip-solidworks", action="store_true")
    parser.add_argument("--skip-nx", action="store_true")
    parser.add_argument("--skip-ansys", action="store_true")
    args = parser.parse_args()

    # Resolve output root — all runs go under demo_output/<timestamp>/
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output:
        output_root = Path(args.output) / ts
    else:
        output_root = Path.cwd() / "demo_output" / ts
    output_root.mkdir(parents=True, exist_ok=True)

    reporter = DemoReporter(output_root)

    run_sw = not args.skip_solidworks and not args.ansys_only
    run_nx = not args.skip_nx and not args.ansys_only
    run_ansys = not args.skip_ansys and not args.cad_only

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  SeekFlow Engineering Tools — Capability Demo{RESET}")
    print(f"{'='*60}")
    print(f"  Output:  {output_root}")
    print(f"  ANSYS:   {'ON' if run_ansys else 'OFF'}")
    print(f"  SW:      {'ON' if run_sw else 'OFF'}")
    print(f"  NX:      {'ON' if run_nx else 'OFF'}")

    if run_nx:
        import subprocess
        # Start NX bridge
        print(f"\n{CYAN}--- Starting NX Bridge ---{RESET}")
        try:
            subprocess.Popen(
                [NX_RUNNER,
                 str(Path(__file__).resolve().parent /
                     "src/seekflow_engineering_tools/nx/nx_bridge_bootstrap.py")],
                env={**os.environ, "NX_JOB_ROOT": str(_nx_job_dir())},
            )
            print("  NX Bridge launched")
            time.sleep(4)  # Let it start
        except Exception as e:
            print(f"  {YELLOW}NX Bridge failed to start: {e}{RESET}")

    # ── ANSYS ────────────────────────────────────────────────────────
    if run_ansys:
        print(f"\n{CYAN}{'='*60}{RESET}")
        print(f"{CYAN}  ANSYS 18.1 — Finite Element Analyses{RESET}")
        print(f"{CYAN}{'='*60}{RESET}")

        reporter.run("ANSYS", "Static cantilever beam", lambda: ansys_static_beam(output_root))
        reporter.run("ANSYS", "Plate with hole (stress concentration)", lambda: ansys_plate_hole(output_root))
        reporter.run("ANSYS", "Steady-state thermal", lambda: ansys_thermal(output_root))
        reporter.run("ANSYS", "Modal analysis (natural freq)", lambda: ansys_modal(output_root))
        reporter.run("ANSYS", "Euler buckling (stability)", lambda: ansys_buckling(output_root))
        reporter.run("ANSYS", "Bilinear plasticity (nonlinear)", lambda: ansys_plastic(output_root))

    # ── SolidWorks ───────────────────────────────────────────────────
    if run_sw:
        print(f"\n{CYAN}{'='*60}{RESET}")
        print(f"{CYAN}  SolidWorks 2025 — CAD Models{RESET}")
        print(f"{CYAN}{'='*60}{RESET}")

        reporter.run("SolidWorks", "Simple box (1 feature)", lambda: sw_simple_box(output_root / "sw"))
        reporter.run("SolidWorks", "Flanged hub (flange+boss+bore+bolts)", lambda: sw_flanged_hub(output_root / "sw"))
        reporter.run("SolidWorks", "Gear — star polygon", lambda: sw_gear_star(output_root / "sw"))
        reporter.run("SolidWorks", "Gear — true involute", lambda: sw_gear_involute(output_root / "sw"))

    # ── NX ───────────────────────────────────────────────────────────
    if run_nx:
        print(f"\n{CYAN}{'='*60}{RESET}")
        print(f"{CYAN}  NX 12.0 — CAD Models (Job Queue Bridge){RESET}")
        print(f"{CYAN}{'='*60}{RESET}")

        reporter.run("NX", "Simple block", lambda: nx_simple_block(output_root / "nx"))
        reporter.run("NX", "Block with through-hole", lambda: nx_block_with_hole(output_root / "nx"))
        reporter.run("NX", "L-bracket (boolean unite)", lambda: nx_l_bracket(output_root / "nx"))
        reporter.run("NX", "Stepped block (multi-body unite)", lambda: nx_stepped_block(output_root / "nx"))

    # ── Finalize ─────────────────────────────────────────────────────
    reporter.summary()

    # Print key metrics for quick inspection
    print(f"{BOLD}Key Engineering Metrics:{RESET}")
    for r in reporter.results:
        if r["_ok"] and "metrics" in r:
            name = r["_name"]
            m = r["metrics"]
            highlights = []
            if "max_displacement_mm" in m:
                highlights.append(f"d_max={m['max_displacement_mm']:.4f}mm")
            if "stress_concentration_kt" in m:
                highlights.append(f"Kt={m['stress_concentration_kt']:.3f}")
            if "tmid_c" in m:
                highlights.append(f"Tmid={m['tmid_c']:.1f}C")
            if "max_plastic_strain" in m:
                highlights.append(f"eps_pl={m['max_plastic_strain']:.4f}")
            if "size" in r:
                highlights.append(f"file={r['size']}B")
            if "size_sldprt" in r:
                highlights.append(f"sldprt={r['size_sldprt']}B")
            if highlights:
                print(f"  {CYAN}{name:<45s}{RESET} {', '.join(highlights)}")


if __name__ == "__main__":
    main()
