"""Data-quality audit: request text params vs measured IR params across all tasks."""
from __future__ import annotations
import json, sys, glob, os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "_param_experiment"))
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))

from validate_req_params import extract_requirements  # noqa: E402
import mcp_tools as mt  # noqa: E402

OUT = ROOT / "app" / "text-to-cad" / "server" / "output"

def measure(base: str) -> dict:
    agg = {}
    for fn in (mt.measure_disc_dimensions, mt.count_fir_tree_slots,
               mt.measure_fir_tree_slot_profile, mt.check_slot_pitch_and_ligament,
               mt.check_slot_depth_and_rim):
        try:
            agg.update(fn({"base_dir": base}))
        except Exception:
            pass
    return agg

tasks = sorted(p.name for p in OUT.iterdir() if p.is_dir() and (p / "raw_fixed.json").exists())
print(f"tasks with raw_fixed: {len(tasks)}")

problems = []
for tid in tasks:
    base = str(OUT / tid)
    req_path = OUT / tid / "request.json"
    if not req_path.exists():
        continue
    req = json.loads(req_path.read_text(encoding="utf-8"))
    text = req.get("text", "") or ""
    if not text:
        problems.append({"task_id": tid, "issue": "request.text empty"})
        continue
    extracted = extract_requirements(text)
    if not extracted:
        problems.append({"task_id": tid, "issue": "no params extracted from request", "extracted": extracted})
        continue
    agg = measure(base)
    actuals = {
        "outer_diameter_mm": agg.get("outer_diameter_mm"),
        "bore_diameter_mm": agg.get("bore_diameter_mm"),
        "axial_thickness_mm": agg.get("axial_thickness_mm"),
        "hub_half_mm": agg.get("hub_half_thickness_mm"),
        "rim_half_mm": agg.get("rim_half_thickness_mm"),
        "slots": agg.get("count"),
        "teeth_count": agg.get("teeth_count"),
        "slot_depth_mm": agg.get("slot_depth_mm"),
        "throat_half_width_mm": agg.get("throat_half_width_mm"),
        "root_fillet_mm": agg.get("root_fillet_mm"),
    }
    tol = {"outer_diameter_mm": 5, "bore_diameter_mm": 5, "axial_thickness_mm": 3,
           "hub_half_mm": 3, "rim_half_mm": 3, "slot_depth_mm": 2,
           "throat_half_width_mm": 0.5, "root_fillet_mm": 0.3}
    for k, exp in extracted.items():
        act = actuals.get(k)
        if act is None:
            continue
        if k in ("slots", "teeth_count", "holes", "grooves"):
            ok = int(act) == int(exp)
        else:
            ok = abs(float(act) - float(exp)) <= tol.get(k, 0.5)
        if not ok:
            problems.append({"task_id": tid, "issue": f"param mismatch {k}", "expected": exp, "actual": act})

print(f"\n===== REQUEST vs IR mismatches ({len(problems)}) =====")
for p in problems:
    print(json.dumps(p, ensure_ascii=False))
