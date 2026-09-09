import ast, re
from pathlib import Path

log = Path(r"E:\text_to_cad_improve\auto_detection_process\_replay_with_llm_parallel.log").read_text(encoding="utf-8", errors="replace")
failures = []
for line in log.splitlines():
    line = line.strip()
    if line.startswith("{'task':"):
        try:
            d = ast.literal_eval(line)
            failures.append((d["task"], d["seed"]))
        except Exception:
            pass
print("parsed failures:", len(failures))

has_raw = []
for t in ["T25","T26","T27","T28","T29","T30","T31","T32"]:
    for s in range(10):
        p = Path(r"E:\text_to_cad_improve\auto_detection_process\_main_experiment\output\runs\full_agentic") / t / ("seed_%d"%s) / "latest" / "llm_raw.json"
        if p.exists():
            has_raw.append((t,s))
ok = [x for x in has_raw if x not in failures]
print("processed:", len(has_raw), "ok:", len(ok))
print("ok seeds:", ["%s-%d"%(t,s) for t,s in sorted(ok)])
