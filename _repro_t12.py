import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process")
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server")

from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from _main_experiment.config import default_experiment_config
from _main_experiment.schemas import TaskSpec
from _main_experiment.llm import OpenAICompatToolClient
from _main_experiment.pipeline import BenchLlmCaller
import agentic_l2

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
route = json.loads((ROOT / "_main_experiment/output/_minimax_m3_40/runs/full_agentic_minimax_m3/T12/seed_0/latest/route_plan.json").read_text(encoding="utf-8"))
tasks = json.loads((ROOT / "_main_experiment/output/tasks.json").read_text(encoding="utf-8"))
task = TaskSpec.model_validate(next(t for t in tasks if t["task_id"] == "T12"))

config = default_experiment_config().model_copy(update={"llm": default_experiment_config().llm.model_copy(update={"model": "MiniMax-M3", "base_url": "https://api.minimax.chat/v1", "api_key_env": "MINIMAX_API_KEY"})})
llm_cfg = config.llm.model_copy(update={"seed": 0})
usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
caller = BenchLlmCaller(OpenAICompatToolClient(), llm_cfg, usage)
lmc = LlmModelConfig(
    model=llm_cfg.model, base_url=llm_cfg.base_url, timeout_s=llm_cfg.timeout_s,
    temperature=llm_cfg.temperature if llm_cfg.temperature is not None else 0.3,
    seed=llm_cfg.seed, api_key_env=llm_cfg.api_key_env,
)
out = ROOT / "_main_experiment/output/_repro_t12"
out.mkdir(parents=True, exist_ok=True)
try:
    raw = agentic_l2.run_agentic_l2(
        task.prompt, None, caller=caller, llm_model_config=lmc, out_dir=out, usage=usage)
    print("OK raw nodes:", len(raw.get("nodes", [])))
except Exception:
    traceback.print_exc()

