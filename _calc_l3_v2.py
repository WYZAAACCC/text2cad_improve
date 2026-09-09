import ast
from pathlib import Path
from collections import Counter

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
c1 = Counter((x["task"], x["seed"]) for x in f1)
c3 = Counter((x["task"], x["seed"]) for x in f3)
print("f1:", len(f1), "f3:", len(f3))

for t in range(19, 31):
    tid = "T%02d" % t
    fails = 0
    for s in range(10):
        if (tid, s) in c1 or (tid, s) in c3:
            fails += 1
    print("%s: %d/10 (fails=%d)" % (tid, 10 - fails, fails))

total_f = sum(1 for t in range(19,31) for s in range(10) if (("T%02d"%t),s) in c1 or (("T%02d"%t),s) in c3)
print("L3 total ok:", 120 - total_f, "/120 =", round((120-total_f)/120, 4))

