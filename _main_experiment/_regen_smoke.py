"""Parallel smoke for parameter-regeneration infrastructure (one perturbation per task)."""

from __future__ import annotations

import collections
import json
import multiprocessing
import pathlib


def _run_one(payload: dict) -> dict:
    from _main_experiment.config import default_experiment_config
    from _main_experiment.suites import regen
    config = default_experiment_config()
    from _main_experiment.aggregate import load_tasks
    task = next(t for t in load_tasks(config) if t.task_id == payload["task_id"])
    try:
        return regen.run_perturbation(task, payload, config)
    except Exception as exc:  # noqa: BLE001
        return {"perturbation_id": payload["perturbation_id"], "error": str(exc)[:300]}


def main() -> int:
    from _main_experiment.config import default_experiment_config
    config = default_experiment_config()
    from _main_experiment.aggregate import load_tasks
    tasks = load_tasks(config)
    by_task = collections.defaultdict(list)
    for p in json.loads(pathlib.Path(
            config.resolved_output_root() / "suites" / "regen" / "tasks.json"
    ).read_text(encoding="utf-8")):
        by_task[p["task_id"]].append(p)
    wanted = {"T09_P000", "T24_P000", "T31_P000"}
    subset = [p for p in json.loads(pathlib.Path(
            config.resolved_output_root() / "suites" / "regen" / "tasks.json"
    ).read_text(encoding="utf-8")) if p["perturbation_id"] in wanted]
    print("smoke perturbations:", len(subset), flush=True)
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=4) as pool:
        results = list(pool.imap_unordered(_run_one, subset))
    for r in sorted(results, key=lambda x: x.get("perturbation_id", "")):
        if "error" in r:
            print(r.get("perturbation_id"), "EXCEPTION", r["error"], flush=True)
        else:
            print(r.get("perturbation_id"), "regen=", r.get("regenerated_ok"),
                  "quality=", r.get("quality_ok"),
                  "reason=", (r.get("reason") or "")[:80], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
