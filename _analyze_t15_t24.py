import json
from pathlib import Path
from collections import Counter

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
RUNS = ROOT / "_main_experiment" / "output" / "runs" / "full_agentic"
TASKS = ["T%02d" % i for i in range(15, 25)]

stage = Counter()
stop = Counter()
before_codes = Counter()
has_raw = 0
total = 0
for t in TASKS:
    for s in range(10):
        d = RUNS / t / ("seed_%d" % s) / "latest"
        rp = d / "run.json"
        if not rp.exists():
            continue
        total += 1
        r = json.loads(rp.read_text(encoding="utf-8"))
        stage[r.get("error_stage") or "success"] += 1
        if (d / "llm_raw.json").exists():
            has_raw += 1
        if not r.get("ok"):
            rs = d / "repair_summary.json"
            if rs.exists():
                stop[json.loads(rs.read_text(encoding="utf-8"))["outcome"]["stop_code"]] += 1
            vi = d / "validation_initial.json"
            if vi.exists():
                for i in json.loads(vi.read_text(encoding="utf-8")).get("issues", []):
                    before_codes[i.get("code")] += 1

print("total run.json:", total, "with llm_raw:", has_raw)
print("stage:", dict(stage))
print("stop:", dict(stop))
print("validation_initial codes:", dict(before_codes))
