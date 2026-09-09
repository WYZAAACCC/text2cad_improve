import json
import sys
from pathlib import Path
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process")
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src")
from seekflow_engineering_tools.generative_cad.validation_kernel import run_validation
from seekflow_engineering_tools.generative_cad.repair_kernel.engine import repair_documents
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad

d = Path(r"E:\text_to_cad_improve\auto_detection_process\_main_experiment\output\_qwen3_7_monitor10\runs\full_agentic_qwen3_7_plus\T01\seed_0\latest")
raw = json.loads((d / "llm_raw.json").read_text(encoding="utf-8"))
reg = default_registry()
res = repair_documents(raw, run_validation(raw), dialect_registry=reg)
print("autofix ok:", res.run.report.ok)
if res.run.report.ok:
    out = d.parent / "plane_fix_probe2"
    out.mkdir(exist_ok=True)
    rr = run_canonical_gcad(res.run.canonical, out_step=out / "output.step", metadata_path=out / "output.metadata.json", validation_seed=res.run.bundle.to_metadata_dict(), require_full_validation_seed=False)
    print("runtime ok:", rr.ok, "err:", (rr.error or "")[:200])
else:
    for i in res.run.report.issues[:5]: print(" ", i.code, i.message)

