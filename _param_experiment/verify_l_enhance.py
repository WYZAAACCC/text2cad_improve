"""临时验证：L 增强（prompt 全文 + 逐次工具调用轨迹）真实 pipeline 集成。"""
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

task_id = "verify_la_" + uuid.uuid4().hex[:8]
text = _text(500, 120, 76, 38, 30, 48, 2, 250, 24, 4.0, 1.0)
print(f"RUN task_id={task_id}")
main._run_pipeline(task_id, text=text, force_route="generative_cad_ir")

d = main.OUT_ROOT / task_id
print("DIR", d)
ok_all = True

def _chk(name, cond, detail=""):
    global ok_all
    print(f"{name:28s}", "OK " if cond else "FAIL", detail)
    ok_all = ok_all and bool(cond)

_chk("prompt_full_l2.json", (d / "prompt_full_l2.json").exists())
if (d / "prompt_full_l2.json").exists():
    p2 = json.loads((d / "prompt_full_l2.json").read_text(encoding="utf-8"))
    _chk("prompt_full_l2 含 system+user",
         len(p2) == 2 and p2[0]["role"] == "system" and p2[1]["role"] == "user",
         f"roles={[m['role'] for m in p2]}")
    _chk("prompt_full_l2 user 含参数化注入块",
         "PARAMETRIC PROFILE CONSTRUCTION" in p2[1]["content"],
         f"user_chars={len(p2[1]['content'])}")

_chk("tool_calls.json", (d / "tool_calls.json").exists())
if (d / "tool_calls.json").exists():
    calls = json.loads((d / "tool_calls.json").read_text(encoding="utf-8"))
    _chk("tool_calls 条目完整", all(
        all(k in r for k in ("ts", "tool_name", "model", "prompt_chars", "prompt_hash",
                             "tool_schema_hash", "ok", "elapsed_s"))
        for r in calls), f"count={len(calls)} tools={[r['tool_name'] for r in calls]}")
    _chk("tool_calls L2 出参摘要",
         any(r.get("tool_name") != "emit_repair_patch" and "result_keys" in r for r in calls))
    repair = [r for r in calls if r.get("tool_name") == "emit_repair_patch"]
    _chk("repair 内联全文(如有)", all("prompt_messages" in r for r in repair),
         f"repair_calls={len(repair)}")
    _chk("tool_calls 全部成功", all(r.get("ok") for r in calls))

if (d / "pipeline_log.json").exists():
    log = json.loads((d / "pipeline_log.json").read_text(encoding="utf-8"))
    tc = log.get("tool_calls", {})
    _chk("pipeline_log.tool_calls 统计",
         "count" in tc and "ok" in tc and "failed" in tc and "total_elapsed_s" in tc,
         str(tc))

print("ALL", "OK" if ok_all else "FAIL")
