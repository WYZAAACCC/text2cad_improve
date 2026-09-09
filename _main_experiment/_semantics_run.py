"""Parallel runner for the 320 semantically-equivalent instruction suite (agentic)."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import pathlib
import time


def _run_one(payload: dict) -> dict:
    from _main_experiment.aggregate import load_tasks
    from _main_experiment.config import default_experiment_config
    from _main_experiment.paths import run_dir
    from _main_experiment.pipeline import run_experiment_task
    from _main_experiment.metrics.semantics import (
        SemanticMetricsComputer,
        parameter_extraction_consistency_vs_golden,
    )
    from _main_experiment.schemas import MethodSpec
    from _main_experiment.utils import atomic_write_json

    config = default_experiment_config()
    config = config.model_copy(update={
        "llm": config.llm.model_copy(update={"thinking": {"type": "disabled"}}),
    })
    task = next(t for t in load_tasks(config) if t.task_id == payload["task_id"])
    spec = task.model_copy(update={"prompt": payload["prompt"]})
    method = MethodSpec(
        method_id=f"semantics_agentic_{payload['semantic_id']}",
        display_name="semantics_agentic",
        llm=config.llm,
        flags={"agentic": True, "force_generative": True},
    )
    try:
        run = run_experiment_task(spec, method, seed=0, config=config)
        run_path = run_dir(method.method_id, spec.task_id, seed=0, config=config)
        sem_metrics = SemanticMetricsComputer().compute(
            run_dir=run_path,
            task_spec=spec,
            run_result=run,
            config=config,
        )
        gold_metric = parameter_extraction_consistency_vs_golden(
            run_path,
            spec.gold.canonical_ir_path.parent,
            spec.normalized_params,
            length_tolerance=config.eval.length_tolerance_mm,
        )
        metrics = {m.metric_id: m.value for m in sem_metrics}
        notes = []
        if gold_metric is not None:
            try:
                notes = json.loads(gold_metric.notes or "[]")
            except Exception:
                notes = []
        metric_models = [
            m.model_dump(mode="json")
            for m in sem_metrics
            if m.metric_id != "parameter_extraction_accuracy"
        ]
        if gold_metric is not None:
            metric_models.append(gold_metric.model_dump(mode="json"))
        atomic_write_json(run_path / "metrics.json", metric_models)
        checked = matched = skipped = 0
        for d in notes:
            exp = d.get("expected")
            act = d.get("actual")
            if act is None:
                skipped += 1
                continue
            if isinstance(exp, (int, float)) and isinstance(act, (int, float)) \
                    and exp > 0 and act <= 0:
                skipped += 1
                continue
            checked += 1
            if d.get("ok"):
                matched += 1
        clean_consistent = checked > 0 and matched == checked
        return {
            "semantic_id": payload["semantic_id"],
            "task_id": payload["task_id"],
            "category": payload["category"],
            "param_consistent": (
                gold_metric is not None and gold_metric.value == 1.0
            ),
            "param_consistent_clean": clean_consistent,
            "param_checked_clean": checked,
            "param_matched_clean": matched,
            "param_skipped_invalid": skipped,
            "fdg_isomorphic": bool(metrics.get("fdg_node_f1") == 1.0
                                   and metrics.get("fdg_edge_f1") == 1.0),
            "engineering_ok": run.ok,
            "status": run.status.value,
            "error_stage": run.error_stage,
            "error_message": (run.error_message or "")[:200],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "semantic_id": payload["semantic_id"],
            "task_id": payload["task_id"],
            "category": payload["category"],
            "param_consistent": False,
            "fdg_isomorphic": False,
            "engineering_ok": False,
            "status": "failed",
            "error_stage": "harness",
            "error_message": str(exc)[:200],
        }


def _read_done(results_path: pathlib.Path) -> set[str]:
    if not results_path.exists():
        return set()
    done: set[str] = set()
    for line in results_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if rec.get("status") == "completed":
                done.add(rec["semantic_id"])
        except Exception:
            continue
    return done


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--category", default=None,
                        help="只跑指定语义改写类别（baseline/order_change/term_swap/unit_mix/"
                             "ratio_abs/fuzzy/split_sentence/table_conflict）")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args(argv)

    from _main_experiment.config import default_experiment_config
    from _main_experiment.suites import semantics
    from _main_experiment.suites.base import write_collection

    config = default_experiment_config()
    items = json.loads(
        (config.resolved_output_root() / "suites" / "semantics" / "tasks.json")
        .read_text(encoding="utf-8"))
    if args.category:
        items = [i for i in items if i["category"] == args.category]
    if args.limit:
        items = items[: args.limit]
    results_path = (config.resolved_output_root() / "suites" / "semantics"
                    / "semantics_results_agentic.jsonl")
    done = set() if args.no_resume else _read_done(results_path)
    pending = [i for i in items if i["semantic_id"] not in done]
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
            if i % 50 == 0 or i == len(pending):
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
    aggregate = semantics.aggregate(records)
    root = config.resolved_output_root() / "suites" / "semantics"
    paths = write_collection(root, "semantics_320_agentic", "semantics_agentic_v1",
                             records, aggregate, config=config,
                             prefix="semantics_agentic")
    print("collection ->", paths["manifest"], flush=True)
    print("aggregate:", json.dumps(aggregate, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
