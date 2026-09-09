"""Rerun only MCP-failed current-main samples with outer MCP feedback repair.

The selected 120-run multi-agent+inner set comes from main_400_seed0to9 with
seeds 6/7/8. Its five MCP-failed samples are:
  T24:6, T26:6, T26:7, T30:7, T30:8
This script runs those exact samples under method flags that enable
outer_feedback_repair=True and writes them to an isolated output root.
"""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

from _main_experiment.config import default_experiment_config
from _main_experiment.runner import run_task
from _main_experiment.schemas import MethodSpec

ROOT = Path(__file__).resolve().parent
OUT_ROOT = ROOT / "_main_experiment" / "output" / "_ablation_current_120_full_outer_v2"

TARGETS = [
    ("T24", 6),
    ("T26", 6),
    ("T26", 7),
    ("T30", 7),
    ("T30", 8),
]


def _worker(payload: dict) -> dict:
    from _main_experiment.aggregate import load_tasks
    from _main_experiment.schemas import TaskSpec

    task_id, seed = payload["task"], int(payload["seed"])
    default_cfg = default_experiment_config()
    task = next(t for t in load_tasks(default_cfg) if t.task_id == task_id)
    task = TaskSpec.model_validate(task.model_dump(mode="json"))
    config = default_cfg.model_copy(update={
        "output_root": OUT_ROOT,
        "llm": default_cfg.llm.model_copy(update={
            "thinking": {"type": "disabled"},
        }),
    })
    method = MethodSpec(
        method_id="ablation_current_full_outer",
        display_name="完整框架（含外层MCP反馈修复）",
        llm=config.llm,
        flags={
            "agentic": True,
            "force_generative": True,
            "repair_enabled": True,
            "deterministic_autofix_enabled": True,
            "outer_feedback_repair": True,
        },
    )
    result = run_task(task, method, seed, config)
    return {
        "task": task_id,
        "seed": seed,
        "ok": bool(result.ok),
        "status": result.status.value,
        "error_stage": result.error_stage,
        "error_message": (result.error_message or "")[:300],
    }


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    jobs = [{"task": t, "seed": s} for t, s in TARGETS]
    ctx = multiprocessing.get_context("spawn")
    records = []
    with ctx.Pool(processes=len(jobs), maxtasksperchild=1) as pool:
        for i, rec in enumerate(pool.imap_unordered(_worker, jobs), 1):
            records.append(rec)
            print(f"progress {i}/{len(jobs)} {rec['task']}:{rec['seed']} "
                  f"ok={rec['ok']} stage={rec['error_stage']}", flush=True)
    records.sort(key=lambda r: (r["task"], r["seed"]))
    (OUT_ROOT / "outer_records.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in records:
        print(r["task"], r["seed"], "ok", r["ok"], "stage", r["error_stage"],
              "err", r["error_message"][:160], flush=True)
    print("saved", OUT_ROOT / "outer_records.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
