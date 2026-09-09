"""Parallel full run for the 800-perturbation regeneration suite.

Uses multiprocessing (spawn) so OCP/CAD state never crosses threads.
Results are appended to regen_results.jsonl for crash-safe resume.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import pathlib
import time


def _run_one(payload: dict) -> dict:
    from _main_experiment.aggregate import load_tasks
    from _main_experiment.config import default_experiment_config
    from _main_experiment.suites import regen

    config = default_experiment_config()
    task = next(t for t in load_tasks(config) if t.task_id == payload["task_id"])
    try:
        res = regen.run_perturbation(task, payload, config)
        res["ok"] = bool(res.get("regenerated_ok") and res.get("quality_ok"))
        return res
    except Exception as exc:  # noqa: BLE001
        return {"perturbation_id": payload["perturbation_id"],
                "task_id": payload["task_id"],
                "category": payload["category"], "ok": False,
                "error": str(exc)[:300]}


def _read_done(results_path: pathlib.Path) -> set[str]:
    if not results_path.exists():
        return set()
    done: set[str] = set()
    for line in results_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            done.add(json.loads(line)["perturbation_id"])
        except Exception:
            continue
    return done


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args(argv)

    from _main_experiment.config import default_experiment_config
    from _main_experiment.suites.base import write_collection
    from _main_experiment.suites import regen

    config = default_experiment_config()
    tasks_file = config.resolved_output_root() / "suites" / "regen" / "tasks.json"
    perturbs = json.loads(tasks_file.read_text(encoding="utf-8"))
    if args.limit:
        perturbs = perturbs[: args.limit]
    results_path = config.resolved_output_root() / "suites" / "regen" / "regen_results.jsonl"
    done = set() if args.no_resume else _read_done(results_path)
    pending = [p for p in perturbs if p["perturbation_id"] not in done]
    print(f"total={len(perturbs)} done={len(perturbs) - len(pending)} "
          f"pending={len(pending)} workers={args.workers}", flush=True)
    if not pending:
        print("nothing to run", flush=True)
        return 0

    started = time.monotonic()
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=args.workers, maxtasksperchild=4) as pool:
        for i, res in enumerate(pool.imap_unordered(_run_one, pending), 1):
            with results_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            if i % 50 == 0 or i == len(pending):
                elapsed = time.monotonic() - started
                rate = i / elapsed
                eta = (len(pending) - i) / rate if rate > 0 else 0
                ok = sum(1 for line in results_path.read_text(encoding="utf-8").splitlines()
                         if line.strip() and json.loads(line).get("ok"))
                print(f"progress {i}/{len(pending)} ok={ok} "
                      f"elapsed={elapsed/60:.1f}min eta={eta/60:.1f}min", flush=True)

    records = []
    for line in results_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    aggregate = regen.aggregate(records)
    root = config.resolved_output_root() / "suites" / "regen"
    paths = write_collection(root, "regen_800", "regen_v1", records,
                             aggregate, config=config, prefix="regen")
    print("collection ->", paths["manifest"], flush=True)
    print("aggregate:", json.dumps(aggregate, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
