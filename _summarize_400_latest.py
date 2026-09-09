import ast
import json
from collections import Counter
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
RUNS = ROOT / "_main_experiment" / "output" / "runs" / "full_agentic"
TASKS_JSON = ROOT / "_main_experiment" / "output" / "tasks.json"

tasks = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
level_map = {t["task_id"]: t["level"] for t in tasks}

def parse(log_path):
    log = Path(log_path).read_text(encoding="utf-8", errors="replace")
    fs = []
    for line in log.splitlines():
        line = line.strip()
        if line.startswith("{") and "task" in line:
            try:
                fs.append(ast.literal_eval(line))
            except Exception:
                pass
    return fs

f1 = parse(r"E:\text_to_cad_improve\auto_detection_process\_replay_t15_t24.log")
f3 = parse(r"E:\text_to_cad_improve\auto_detection_process\_replay_with_llm_parallel3.log")
fail15_24 = Counter((x["task"], x["seed"]) for x in f1)
fail25_32 = Counter((x["task"], x["seed"]) for x in f3)
f_t14 = parse(r"E:\text_to_cad_improve\auto_detection_process\_replay_t14.log")
fail_t14 = Counter((x["task"], x["seed"]) for x in f_t14)

def runs_ok(tid, s):
    rp = RUNS / tid / ("seed_%d" % s) / "latest" / "run.json"
    return bool(json.loads(rp.read_text(encoding="utf-8")).get("ok"))

rows = []
for t in range(1, 41):
    tid = "T%02d" % t
    for s in range(10):
        if t == 14:
            ok = (tid, s) not in fail_t14
        elif 15 <= t <= 24:
            ok = (tid, s) not in fail15_24
        elif 25 <= t <= 31:
            ok = (tid, s) not in fail25_32
        elif t == 32:
            ok = (tid, s) not in fail25_32 if s <= 2 else runs_ok(tid, s)
        else:
            ok = runs_ok(tid, s)
        rows.append({"task": tid, "seed": s, "level": level_map.get(tid, "?"), "ok": ok})

ok = sum(1 for x in rows if x["ok"])
print("total:", len(rows), "ok:", ok, "rate:", round(ok / len(rows), 4))
print("by level:")
for lv in ["L1", "L2", "L3", "L4"]:
    sub = [x for x in rows if x["level"] == lv]
    o = sum(1 for x in sub if x["ok"])
    print("  %s: %d/%d = %.4f" % (lv, o, len(sub), o / len(sub)))
print("per task:")
for t in range(1, 41):
    tid = "T%02d" % t
    sub = [x for x in rows if x["task"] == tid]
    print("  %s: %d/10" % (tid, sum(1 for x in sub if x["ok"])))

out = ROOT / "_main_experiment" / "output" / "final_400_summary_latest.json"
out.write_text(json.dumps({
    "total": len(rows), "ok": ok, "rate": round(ok / len(rows), 4),
    "by_level": {lv: {"ok": sum(1 for x in rows if x["level"] == lv and x["ok"]),
                     "total": sum(1 for x in rows if x["level"] == lv)} for lv in ["L1","L2","L3","L4"]},
    "rows": rows,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote:", out)

