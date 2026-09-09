import ast
from pathlib import Path
from collections import defaultdict

def parse_ok(log_path):
    log = Path(log_path).read_text(encoding="utf-8", errors="replace")
    failures = []
    for line in log.splitlines():
        line = line.strip()
        if line.startswith("{'task':"):
            try:
                d = ast.literal_eval(line)
                failures.append(d)
            except Exception:
                pass
    return failures

# replay_t15_t24: latest-code replay of T15-T24 (100 processed, 84 ok)
f1 = parse_ok(r"E:\text_to_cad_improve\auto_detection_process\_replay_t15_t24.log")
# replay_with_llm parallel3: latest optimized replay of T25-T32 (73 processed, 45 ok)
f3 = parse_ok(r"E:\text_to_cad_improve\auto_detection_process\_replay_with_llm_parallel3.log")

def ok_map(failures, tasks):
    ok = {}
    for t in tasks:
        for s in range(10):
            key = (t, s)
            fail_set = {(f.get("task"), f.get("seed")) for f in failures}
            ok[key] = (t, s) not in fail_set
    return ok

t15_24 = ok_map(f1, ["T%02d" % i for i in range(15, 25)])
t25_32 = ok_map(f3, ["T25","T26","T27","T28","T29","T30","T31","T32"])

# L3 = T19-T30
l3_tasks = ["T%02d" % i for i in range(19, 31)]
per = {}
for t in l3_tasks:
    okc = 0
    for s in range(10):
        if t in t15_24:
            okc += 1 if t15_24[(t,s)] else 0
        elif t in t25_32:
            okc += 1 if t25_32[(t,s)] else 0
    per[t] = okc
print("L3 per-task (latest replay):")
for t in l3_tasks:
    print("  %s: %d/10" % (t, per[t]))
print("L3 total:", sum(per.values()), "/ 120 =", round(sum(per.values())/120, 4))
