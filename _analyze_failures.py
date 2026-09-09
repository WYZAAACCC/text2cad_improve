import ast
from pathlib import Path
from collections import Counter, defaultdict

log = Path(r"E:\text_to_cad_improve\auto_detection_process\_replay_with_llm_parallel2.log").read_text(encoding="utf-8", errors="replace")
failures = []
for line in log.splitlines():
    line = line.strip()
    if line.startswith("{'task':"):
        try:
            d = ast.literal_eval(line)
            if not d.get("ok"):
                failures.append(d)
        except Exception:
            pass

print("total failures:", len(failures))
cats = Counter()
gate_groups = Counter()
giveup_nodes = Counter()
for f in failures:
    stop = f.get("stop")
    if stop == "success":
        cats["mcp_gate_failed"] += 1
        key = "|".join(sorted(f.get("gate_failed") or []))
        gate_groups[key] += 1
    elif stop == "give_up":
        cats["give_up"] += 1
        r = f.get("reason", "")
        if "runtime repair agent gave up" in r:
            giveup_nodes["runtime_gave_up"] += 1
    elif stop == "runtime_attempts_exhausted":
        cats["runtime_attempts_exhausted"] += 1
    else:
        cats[stop] += 1

print("category counts:", dict(cats))
print("\ngate failure groups:")
for k, v in sorted(gate_groups.items(), key=lambda x: -x[1]):
    print("  %3d  %s" % (v, k))

print("\nper-task failure counts:")
per_task = Counter(f["task"] for f in failures)
for t in ["T25","T26","T27","T28","T29","T30","T31","T32"]:
    print("  %s: %d" % (t, per_task.get(t, 0)))
