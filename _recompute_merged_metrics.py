"""Recompute metrics.json for the merged 400 main-experiment success rows.

The merged 400 uses replay outputs for T14-T31 (and T32 seeds 0-2) which do not
have metrics.json. This script runs the same metric computers on those run dirs
and writes metrics.json back into each replay run directory. It also audits how
many merged successes end up with metrics.
"""

from __future__ import annotations

import json
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"
sys.path.insert(0, str(ROOT))

from _main_experiment.config import default_experiment_config  # noqa: E402
from _main_experiment.metrics.compute import compute_all_metrics  # noqa: E402
from _main_experiment.schemas import RunResult, TaskSpec  # noqa: E402

_CONFIG = default_experiment_config()
_TASKS: dict[str, dict] = {}


def _init(task_dicts: list[dict]) -> None:
    global _TASKS
    _TASKS = {d["task_id"]: d for d in task_dicts}


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


def compute_one(item: dict) -> dict:
    task = item["task"]
    seed = item["seed"]
    run_dir = merged_run_dir(task, seed)
    spec = TaskSpec.model_validate(_TASKS[task])
    run_result = RunResult(
        run_id=f"merged__{task}__seed{seed}",
        method_id="full_agentic",
        task_id=task,
        seed=seed,
        status="completed",
        ok=True,
        outputs={
            "step": str(run_dir / "output.step"),
            "raw_fixed": str(run_dir / "raw_fixed.json"),
            "canonical_ir": str(run_dir / "canonical_ir.json"),
        },
    )
    try:
        metrics = compute_all_metrics(
            run_dir=run_dir,
            task_spec=spec,
            run_result=run_result,
            config=_CONFIG,
        )
        payload = [m.model_dump(mode="json") for m in metrics]
        (run_dir / "metrics.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"task": task, "seed": seed, "ok": True, "metrics": payload}
    except Exception as exc:  # noqa: BLE001
        return {"task": task, "seed": seed, "ok": False, "error": str(exc)[:300]}


def main() -> None:
    smoke = "--smoke" in sys.argv
    tasks_json = json.loads((OUT / "tasks.json").read_text(encoding="utf-8"))
    final = json.loads((OUT / "final_400_summary_latest.json").read_text(encoding="utf-8"))
    ok_rows = [
        {"task": r["task"], "seed": int(r["seed"])}
        for r in final["rows"]
        if r["ok"]
    ]
    task_dicts = [t for t in tasks_json if t["task_id"] in {x["task"] for x in ok_rows}]

    targets = []
    for item in ok_rows:
        rd = merged_run_dir(item["task"], item["seed"])
        is_replay = "replay" in str(rd)
        if not is_replay:
            continue  # original full_agentic metrics already exist
        targets.append(item)
        if smoke and len(targets) >= 2:
            break

    print(f"targets={len(targets)} ok_rows={len(ok_rows)} smoke={smoke}", flush=True)
    with Pool(
        processes=1 if smoke else 8,
        initializer=_init,
        initargs=(task_dicts,),
    ) as pool:
        results = list(pool.imap_unordered(compute_one, targets))
    ok = sum(1 for r in results if r["ok"])
    print(f"done={len(results)} ok={ok}")
    for r in results:
        if not r["ok"]:
            print("FAIL", r["task"], r["seed"], r.get("error"))

    if not smoke:
        # audit final coverage
        have = 0
        missing = []
        for item in ok_rows:
            if (merged_run_dir(item["task"], item["seed"]) / "metrics.json").exists():
                have += 1
            else:
                missing.append(item)
        print(f"merged_ok_with_metrics={have}/{len(ok_rows)}")
        print("missing", missing[:20])


if __name__ == "__main__":
    main()
