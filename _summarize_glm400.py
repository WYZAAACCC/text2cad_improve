import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process\_main_experiment\output")
batches = {
    "T01-T04": ROOT / "_glm_5_2_T01_T04_40" / "runs" / "full_agentic_glm_5_2",
    "T05-T14": ROOT / "_glm_5_2_T05_T14_100" / "runs" / "full_agentic_glm_5_2",
    "T15-T24": ROOT / "_glm_5_2_T15_T24_100" / "runs" / "full_agentic_glm_5_2",
    "T25-T30": ROOT / "_glm_5_2_T25_T34_100" / "runs" / "full_agentic_glm_5_2",
    "T31-T40": ROOT / "_glm_5_2_T31_T40_100" / "runs" / "full_agentic_glm_5_2",
}
res = {}
for label, root in batches.items():
    for rp in root.rglob("run.json"):
        try:
            d = json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not d.get("task_id"):
            continue
        key = (d["task_id"], d.get("seed", -1))
        # 后写入的批次覆盖（T31-T40 用新批次）
        res[key] = {"ok": bool(d.get("ok")), "task": d["task_id"], "seed": d.get("seed")}

rows = sorted(res.values(), key=lambda x: (x["task"], x["seed"]))
ok = sum(1 for r in rows if r["ok"])
print("total:", len(rows), "ok:", ok, "rate:", round(ok/len(rows), 4))
per = defaultdict(lambda: [0,0])
for r in rows:
    per[r["task"]][0] += 1 if r["ok"] else 0
    per[r["task"]][1] += 1
for t in range(1, 41):
    tid = "T%02d" % t
    print("%s: %d/10" % (tid, per[tid][0]))
