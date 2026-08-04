"""临时验证：真实 pipeline 三项落盘（request.json / canonical_ir.json / pipeline_log.json）。"""
import json
import sys
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "_param_experiment"))

import main  # noqa: E402
from param_sweep_test import _text  # noqa: E402

task_id = "verify_ds_" + uuid.uuid4().hex[:8]
text = _text(500, 120, 76, 38, 30, 48, 2, 250, 24, 4.0, 1.0)
print(f"RUN task_id={task_id}")
main._run_pipeline(task_id, text=text, force_route="generative_cad_ir")

d = main.OUT_ROOT / task_id
print("DIR", d)
for name in ("request.json", "canonical_ir.json", "pipeline_log.json", "output.step"):
    p = d / name
    print(f"{name:18s}", "EXISTS" if p.exists() else "MISSING",
          f"({p.stat().st_size} B)" if p.exists() else "")
if (d / "request.json").exists():
    req = json.loads((d / "request.json").read_text(encoding="utf-8"))
    print("request.text head:", req["text"][:60], "| desc_style:", req.get("desc_style"))
if (d / "canonical_ir.json").exists():
    ir = json.loads((d / "canonical_ir.json").read_text(encoding="utf-8"))
    print("canonical_ir: nodes =", len(ir.get("nodes", [])))
if (d / "pipeline_log.json").exists():
    log = json.loads((d / "pipeline_log.json").read_text(encoding="utf-8"))
    print("pipeline_log: ok =", log["ok"], "| error =", log.get("error"))
    print("pipeline_log.stages keys =", sorted(log.get("stages", {}).keys()))
    want = ["request.json", "canonical_ir.json", "output.step", "raw_fixed.json",
            "req_param_report.json", "validation_report.json"]
    print("pipeline_log.artifacts covered =",
          {w: (w in log.get("artifacts", [])) for w in want})
print("DONE")
