"""Restore the 9 merge-contaminated main-experiment runs with the clean pipeline.

These (task, seed) rows were overwritten by the golden-feedback merge path.
This script re-runs them through the real end-to-end agentic pipeline (no
golden feedback anywhere) and writes the clean artifacts back into the merged
run dirs. Then it recomputes final_400_summary_latest.json from run.json.
"""

from __future__ import annotations

import json
import multiprocessing
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"
sys.path.insert(0, str(ROOT))

TARGETS = [
    ("T19", 0), ("T29", 0), ("T20", 1), ("T23", 2), ("T32", 3),
    ("T31", 0), ("T33", 1), ("T34", 0), ("T36", 3),
]
METHOD_ID = "full_agentic_clean9"
WORKERS = 9


def merged_run_dir(task: str, seed: int) -> Path:
    if task == "T14":
        return OUT / "replay_t14_with_llm" / task / f"seed_{seed}"
    if "T15" <= task <= "T24":
        return OUT / "replay_t15_t24_with_llm" / task / f"seed_{seed}"
    if "T25" <= task <= "T31":
        return OUT / "replay_with_llm" / task / f"seed_{seed}"
    if task == "T32" and seed <= 2:
        return OUT / "replay_with_llm" / task / f"seed_{seed}"
    return OUT / "runs" / "full_agentic" / task / f"seed_{seed}" / "latest"


def _worker(job) -> dict:
    task_dict, method_dict, seed, tmp_root = job
    from _main_experiment.config import default_experiment_config
    from _main_experiment.runner import run_task
    from _main_experiment.schemas import MethodSpec, TaskSpec

    task = TaskSpec.model_validate(task_dict)
    method = MethodSpec.model_validate(method_dict)
    config = default_experiment_config().model_copy(update={
        "output_root": Path(tmp_root).resolve(),
        "llm": method.llm,
    })
    result = run_task(task, method, seed, config)
    src = Path(tmp_root) / "runs" / METHOD_ID / task.task_id / f"seed_{seed}" / "latest"
    dst = merged_run_dir(task.task_id, seed)
    dst.mkdir(parents=True, exist_ok=True)
    for f in dst.iterdir():
        if f.is_file():
            f.unlink()
        else:
            shutil.rmtree(f)
    if src.exists():
        for f in src.iterdir():
            if f.is_dir():
                shutil.copytree(f, dst / f.name, dirs_exist_ok=True)
            else:
                shutil.copy2(f, dst / f.name)
    return {
        "task_id": task.task_id,
        "seed": seed,
        "status": result.status.value,
        "ok": result.ok,
        "error_stage": result.error_stage,
        "error_message": (result.error_message or "")[:200],
    }


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=None,
                    help="comma list of task:seed to restore (default all 9)")
    args = ap.parse_args()
    targets = TARGETS
    if args.tasks:
        targets = []
        for item in args.tasks.split(","):
            t, s = item.strip().split(":")
            targets.append((t, int(s)))
    tasks_json = json.loads((OUT / "tasks.json").read_text(encoding="utf-8"))
    tasks = {t["task_id"]: t for t in tasks_json}
    from _main_experiment.config import default_experiment_config
    from _main_experiment.schemas import MethodSpec
    cfg = default_experiment_config().model_copy(update={
        "llm": default_experiment_config().llm.model_copy(update={
            "thinking": {"type": "disabled"},
        }),
    })
    method = MethodSpec(method_id=METHOD_ID, display_name=METHOD_ID,
                        llm=cfg.llm, flags={"agentic": True, "force_generative": True})
    md = method.model_dump(mode="json")
    jobs = []
    for task, seed in targets:
        tmp = Path(tempfile.mkdtemp(prefix=f"clean9_{task}_{seed}_"))
        jobs.append((tasks[task], md, seed, str(tmp)))
    ctx = multiprocessing.get_context("spawn")
    done = []
    with ctx.Pool(processes=WORKERS, maxtasksperchild=1) as pool:
        for i, r in enumerate(pool.imap_unordered(_worker, jobs, chunksize=1), 1):
            done.append(r)
            ok = sum(1 for d in done if d.get("ok"))
            print(f"progress {i}/{len(jobs)} ok={ok} last={r['task_id']}/seed{r['seed']} "
                  f"ok={r['ok']} stage={r['error_stage']}", flush=True)
    ok = sum(1 for d in done if d.get("ok"))
    print(f"done={len(done)} ok={ok}")
    (OUT / "clean9_restore_report.json").write_text(
        json.dumps({"targets": TARGETS, "records": done}, ensure_ascii=False, indent=2),
        encoding="utf-8")


if __name__ == "__main__":
    main()
