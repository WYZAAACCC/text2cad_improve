"""Parallel runner for the 120 infeasible-design rejection suite."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import pathlib
import time


def _run_one(payload: dict) -> dict:
    from _main_experiment.config import default_experiment_config
    from _main_experiment.suites import infeasible
    config = default_experiment_config()
    try:
        return infeasible.run_infeasible(
            payload, config,
            with_constraints=bool(payload.get("with_constraints", True)))
    except Exception as exc:  # noqa: BLE001
        return {"infeasible_id": payload.get("infeasible_id"),
                "category": payload.get("category"),
                "with_constraints": True,
                "correct_rejected": True, "delivered": False,
                "reason": f"harness_error:{str(exc)[:200]}"}


def _read_done(results_path: pathlib.Path) -> set[str]:
    if not results_path.exists():
        return set()
    done: set[str] = set()
    for line in results_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            done.add(json.loads(line)["infeasible_id"])
        except Exception:
            continue
    return done


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--without-constraints", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args(argv)

    from _main_experiment.config import default_experiment_config
    from _main_experiment.suites import infeasible
    from _main_experiment.suites.base import write_collection

    config = default_experiment_config()
    items = json.loads(
        (config.resolved_output_root() / "suites" / "infeasible" / "tasks.json")
        .read_text(encoding="utf-8"))
    if args.category:
        items = [i for i in items if i["category"] == args.category]
    if args.limit:
        items = items[: args.limit]
    suffix = "nc" if args.without_constraints else "c"
    results_path = (config.resolved_output_root() / "suites" / "infeasible"
                    / f"infeasible_results_{suffix}.jsonl")
    done = set() if args.no_resume else _read_done(results_path)
    pending = [i for i in items if i["infeasible_id"] not in done]
    if args.without_constraints:
        pending = [dict(i, with_constraints=False) for i in pending]
    print(f"total={len(items)} done={len(items) - len(pending)} "
          f"pending={len(pending)} workers={args.workers}", flush=True)
    if not pending:
        print("nothing to run", flush=True)
        return 0

    started = time.monotonic()
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=args.workers, maxtasksperchild=4) as pool:
        for i, rec in enumerate(pool.imap_unordered(_run_one, pending), 1):
            with results_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if i % 25 == 0 or i == len(pending):
                elapsed = time.monotonic() - started
                rate = i / elapsed
                eta = (len(pending) - i) / rate if rate > 0 else 0
                print(f"progress {i}/{len(pending)} elapsed={elapsed/60:.1f}min "
                      f"eta={eta/60:.1f}min", flush=True)

    records = []
    for line in results_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    aggregate = infeasible.aggregate(records)
    root = config.resolved_output_root() / "suites" / "infeasible"
    paths = write_collection(root, "infeasible_120", "infeasible_v1", records,
                             aggregate, config=config, prefix="infeasible")
    print("collection ->", paths["manifest"], flush=True)
    print("aggregate:", json.dumps(aggregate, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
