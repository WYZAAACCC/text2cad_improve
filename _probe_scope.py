import json, sys
from pathlib import Path
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process")
from seekflow_engineering_tools.generative_cad.repair_kernel.orchestrator import run_generation_loop
from seekflow_engineering_tools.generative_cad.repair_kernel.config import RepairLoopConfig
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from _main_experiment.config import default_experiment_config
from _main_experiment.schemas import MethodSpec, TaskSpec
from _main_experiment.llm import OpenAICompatToolClient
from _main_experiment.pipeline import BenchLlmCaller

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
src = ROOT / "_main_experiment/output/runs/full_agentic/T25/seed_0/latest/llm_raw.json"
raw = json.loads(src.read_text(encoding="utf-8"))
out = ROOT / "_main_experiment/output/replay_with_llm_scope/T25_seed_0"
out.mkdir(parents=True, exist_ok=True)

config = default_experiment_config()
task_specs = json.loads((ROOT / "_main_experiment/output/tasks.json").read_text(encoding="utf-8"))
task_spec = TaskSpec.model_validate(next(t for t in task_specs if t["task_id"] == "T25"))
method = MethodSpec(method_id="scope_probe", display_name="scope_probe", llm=config.llm, flags={"agentic": True})
llm_cfg = config.llm.model_copy(update={"seed": 0})
usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
caller = BenchLlmCaller(OpenAICompatToolClient(), llm_cfg, usage)
loop = run_generation_loop(
    raw,
    out_step=out / "output.step", metadata_path=out / "output.metadata.json",
    dialect_registry=default_registry(),
    config=RepairLoopConfig(max_validation_llm_attempts=3, max_runtime_llm_attempts=2, max_total_llm_attempts=3),
    validation_repair_caller=caller, runtime_repair_caller=caller,
    llm_model_config=llm_cfg, audit_dir=out,
    user_request=task_spec.prompt,
)
print("stop:", loop.outcome.stop_code)
print("reason:", loop.outcome.stop_reason)
print("runtime attempts:", loop.outcome.runtime_llm_attempts)
for p in loop.outcome.rejected_patches:
    print("rejected:", p.get("phase"), p.get("reason"))
