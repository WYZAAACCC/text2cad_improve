import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
RUNS = ROOT / "_main_experiment" / "output" / "runs" / "full_agentic"
TASKS_JSON = ROOT / "_main_experiment" / "output" / "tasks.json"

tasks = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
level_map = {t["task_id"]: t["level"] for t in tasks}

rows = []
for t in range(1, 41):
    tid = "T%02d" % t
    for s in range(10):
        d = RUNS / tid / ("seed_%d" % s) / "latest"
        r = json.loads((d / "run.json").read_text(encoding="utf-8"))
        stop = ""
        rs = d / "repair_summary.json"
        if rs.exists():
            stop = json.loads(rs.read_text(encoding="utf-8"))["outcome"]["stop_code"]
        rows.append({
            "task": tid, "seed": s, "level": level_map.get(tid, "?"),
            "ok": bool(r.get("ok")), "stage": r.get("error_stage") or "success",
            "stop": stop, "msg": (r.get("error_message") or "")[:120],
        })

ok = sum(1 for x in rows if x["ok"])
print("total:", len(rows), "ok:", ok, "rate:", round(ok / len(rows), 4))

print("\\nby level:")
for lv in ["L1", "L2", "L3", "L4"]:
    sub = [x for x in rows if x["level"] == lv]
    o = sum(1 for x in sub if x["ok"])
    print("  %s: %d/%d = %.4f" % (lv, o, len(sub), o / len(sub)))

print("\\nby stage:")
for k, v in Counter(x["stage"] for x in rows).most_common():
    print("  %s: %d" % (k, v))

print("\\nby stop:")
for k, v in Counter(x["stop"] or "(none)" for x in rows).most_common():
    print("  %s: %d" % (k, v))

print("\\nper task:")
for t in range(1, 41):
    tid = "T%02d" % t
    sub = [x for x in rows if x["task"] == tid]
    o = sum(1 for x in sub if x["ok"])
    print("  %s: %d/10" % (tid, o))

summary = {
    "total": len(rows), "ok": ok, "rate": round(ok / len(rows), 4),
    "by_level": {lv: {"ok": sum(1 for x in rows if x["level"] == lv and x["ok"]),
                     "total": sum(1 for x in rows if x["level"] == lv)} for lv in ["L1", "L2", "L3", "L4"]},
    "by_stage": dict(Counter(x["stage"] for x in rows)),
    "by_stop": dict(Counter(x["stop"] or "(none)" for x in rows)),
    "rows": rows,
}
out = ROOT / "_main_experiment" / "output" / "final_400_summary.json"
out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("\\nwrote:", out)

