import json
from pathlib import Path
from collections import Counter

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process\_main_experiment\output\_ds_flash_T21_T30_100\runs\full_agentic_ds_flash")
stops = Counter()
rt_issues = Counter()
rt_nodes = Counter()
samples = []
for rp in ROOT.rglob("run.json"):
    r = json.loads(rp.read_text(encoding="utf-8"))
    if r.get("ok"):
        continue
    d = rp.parent
    rs = d / "repair_summary.json"
    if rs.exists():
        stop = json.loads(rs.read_text(encoding="utf-8"))["outcome"]["stop_code"]
        stops[stop] += 1
    rr = d / "repair" / "runtime" / "attempt_01" / "runtime_report.json"
    if rr.exists():
        rep = json.loads(rr.read_text(encoding="utf-8"))
        for i in rep.get("issues", []):
            rt_issues[i.get("code")] += 1
            rt_nodes[i.get("node_id") or "?"] += 1
        if len(samples) < 5:
            samples.append((r["task_id"], rep.get("issues", [{}])[0].get("code"), rep.get("issues", [{}])[0].get("message", "")[:120]))

print("repair stop:", dict(stops))
print("runtime issue codes:", dict(rt_issues))
print("runtime issue nodes:", dict(rt_nodes))
print("samples:")
for s in samples:
    print("  ", s)
