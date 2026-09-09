import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
sys.path.insert(0, str(ROOT))
TASKS = ["T33", "T34", "T35", "T36", "T37", "T38", "T39", "T40"]

_TASK_MAP = {}

def _init(task_dicts):
    global _TASK_MAP
    _TASK_MAP = {d["task_id"]: d for d in task_dicts}

def build_one(t):
    from _main_experiment.config import default_experiment_config
    from _main_experiment.schemas import TaskSpec
    from _main_experiment.tasks.golden_builder import build_golden_for_task
    task = TaskSpec.model_validate(_TASK_MAP[t])
    try:
        res = build_golden_for_task(task, default_experiment_config())
        return (t, res.get("ok"), res.get("mcp_gate", {}).get("ok"))
    except Exception as exc:
        return (t, False, str(exc)[:200])

def main():
    from _main_experiment.config import default_experiment_config
    from _main_experiment.aggregate import load_tasks
    tasks = load_tasks(default_experiment_config())
    task_dicts = [t.model_dump(mode="json") for t in tasks if t.task_id in TASKS]
    with Pool(processes=8, initializer=_init, initargs=(task_dicts,)) as pool:
        for r in pool.imap_unordered(build_one, TASKS):
            print(r, flush=True)

if __name__ == "__main__":
    main()

