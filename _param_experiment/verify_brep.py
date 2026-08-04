"""临时验证：MBRep（output.brep）真实 pipeline 导出 + BRep 回读体积一致性。"""
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

task_id = "verify_br_" + uuid.uuid4().hex[:8]
text = _text(500, 120, 76, 38, 30, 48, 2, 250, 24, 4.0, 1.0)
print(f"RUN task_id={task_id}")
main._run_pipeline(task_id, text=text, force_route="generative_cad_ir")

d = main.OUT_ROOT / task_id
ok_all = True


def _chk(name, cond, detail=""):
    global ok_all
    print(f"{name:28s}", "OK " if cond else "FAIL", detail)
    ok_all = ok_all and bool(cond)


brep = d / "output.brep"
_chk("output.brep 存在", brep.exists(), f"({brep.stat().st_size//1024} KB)" if brep.exists() else "")
if brep.exists():
    import cadquery as cq
    b = cq.importers.importBrep(str(brep))
    s = cq.importers.importStep(str(d / "output.step"))
    vol_b = sum(sol.Volume() for sol in b.solids().vals())
    vol_s = sum(sol.Volume() for sol in s.solids().vals())
    ratio = abs(vol_b - vol_s) / vol_s if vol_s else -1
    _chk("BRep 回读体积 vs STEP", ratio >= 0 and ratio < 0.001,
         f"brep={vol_b:.3f} step={vol_s:.3f} diff={ratio*100:.4f}%")

print("ALL", "OK" if ok_all else "FAIL")
