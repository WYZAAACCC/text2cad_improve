import ast
from pathlib import Path

def parse_ok(log_path):
    log = Path(log_path).read_text(encoding="utf-8", errors="replace")
    failures = []
    for line in log.splitlines():
        line = line.strip()
        if line.startswith("{'task':"):
            try:
                d = ast.literal_eval(line)
                failures.append(d)
            except Exception as exc:
                print("parse fail:", line[:80], exc)
    return failures

f1 = parse_ok(r"E:\text_to_cad_improve\auto_detection_process\_replay_t15_t24.log")
print("t15_t24 failures parsed:", len(f1))
for f in f1[:5]:
    print(" ", f.get("task"), f.get("seed"), f.get("ok"), f.get("stop"))
f3 = parse_ok(r"E:\text_to_cad_improve\auto_detection_process\_replay_with_llm_parallel3.log")
print("parallel3 failures parsed:", len(f3))
