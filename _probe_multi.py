import json, sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process")

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
TASKS_JSON = ROOT / "_main_experiment" / "output" / "tasks.json"

def run(job):
    t, s = job
    src = ROOT / ("_main_experiment/output/runs/full_agentic/%s/seed_%d/latest/llm_raw.json" % (t, s))
    if not src.exists():
        return (t, s, "no_raw")
    from seekflow_engineering_tools.generative_cad.repair_kernel.orchestrator import run_generation_loop
    from seekflow_engineering_tools.generative_cad.repair_kernel.config import RepairLoopConfig
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
    from _main_experiment.config import default_experiment_config
    from _main_experiment.schemas import TaskSpec
    from _main_experiment.llm import OpenAICompatToolClient
    from _main_experiment.pipeline import BenchLlmCaller

    raw = json.loads(src.read_text(encoding="utf-8"))
    out = ROOT / ("_main_experiment/output/replay_prompt_probe/%s_seed_%d" % (t, s))
    out.mkdir(parents=True, exist_ok=True)
    config = default_experiment_config()
    task_specs = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
    task_spec = TaskSpec.model_validate(next(x for x in task_specs if x["task_id"] == t))
    llm_cfg = config.llm.model_copy(update={"seed": s})
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    caller = BenchLlmCaller(OpenAICompatToolClient(), llm_cfg, usage)
    loop = run_generation_loop(
        raw, out_step=out / "output.step", metadata_path=out / "output.metadata.json",
        dialect_registry=default_registry(),
        config=RepairLoopConfig(max_validation_llm_attempts=3, max_runtime_llm_attempts=2, max_total_llm_attempts=3),
        validation_repair_caller=caller, runtime_repair_caller=caller,
        llm_model_config=llm_cfg, audit_dir=out, user_request=task_spec.prompt,
    )
    return (t, s, loop.outcome.stop_code, loop.outcome.stop_reason, loop.outcome.runtime_llm_attempts,
            [p.get("reason") for p in loop.outcome.rejected_patches])

if __name__ == "__main__":
    jobs = [("T26", 6), ("T27", 2), ("T28", 0), ("T32", 0)]
    with Pool(processes=4) as pool:
        for r in pool.imap_unordered(run, jobs):
            print(r, flush=True)

