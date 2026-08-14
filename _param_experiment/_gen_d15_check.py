"""一次性：用当前 param_templates（确定性模板）生成 D15 涡轮盘并跑完整 pipeline。

用法: .conda/python.exe _param_experiment/_gen_d15_check.py
产物: auto_detection_process/app/text-to-cad/server/output/check_D15/
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
# DEEPSEEK_API_KEY must be set in the environment.
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

import main
import param_templates
from design_families import DESIGN_FAMILIES, build_text

fam = DESIGN_FAMILIES["D15"]
f = fam["features"]
# D15 slot2d 自然结构 v9：mouth=8、depth=21.2（N2 自然深度，不撑满榫底）、slots=40、fr=0.97=fr_limit。
params = {
    "category": "slot", "_tag": "d15_v9",
    "od_mm": fam["od"], "bore_mm": fam["bore"], "thick_mm": fam["thick"],
    "hub_mm": fam["hub"], "rim_mm": fam["rim"],
    "slots": 40, "teeth": f["teeth"], "R_mm": f["R"],
    "depth_mm": 21.2, "throat_half_width_mm": 8.0,
    "fr_mm": 0.97, "form": fam["form"],
    "tfa_deg": 45.0, "ufa_deg": 75.0,
}
print("D15 params:", json.dumps(params, ensure_ascii=False))

doc = param_templates.build(params)
n_upper = None
for comp in doc.get("components", []):
    if comp.get("kind_hint") == "fir_tree_slot_cutter":
        print(f"cutter component root: {comp['root_node']}")
n_nodes = len(doc.get("nodes", []))
print(f"build OK: nodes={n_nodes} comps={len(doc.get('components', []))}")

tid = "check_D15_v9"
out_dir = main.OUT_ROOT / tid
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "llm_raw.json").write_text(
    json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
os.environ["TEMPLATE_L2"] = "1"

text = build_text(fam)
main._tasks[tid] = {"taskId": tid, "status": "pending", "progress": 0,
                    "result": None, "error": None}
main._run_pipeline(tid, text, force_route="generative_cad_ir")

st = main._tasks[tid]
print("\n=== D15 pipeline 结果 ===")
print("status:", st.get("status"))
if st.get("error"):
    print("error:", st.get("error"))
for name in ("output.step", "output.metadata.json", "raw_fixed.json",
             "validation_report.json", "mcp_gate.json", "pipeline_log.json"):
    p = out_dir / name
    if p.exists():
        print(f"  {name}: {p.stat().st_size} bytes")
print("产物目录:", out_dir)
