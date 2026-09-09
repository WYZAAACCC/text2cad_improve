"""Command-line entrypoint for the isolated main experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .aggregate import aggregate_all, load_runs, load_tasks, write_aggregate
from .config import ExperimentConfig, LlmConfig, default_experiment_config
from .paths import experiment_output_root
from .report import write_report
from .runner import run_benchmark
from .schemas import MethodSpec
from .tasks.golden_builder import build_all_golden
from .tasks.registry import write_tasks_file
from .tasks.task_builder import build_task_specs
from .utils import atomic_write_json


def _config(args) -> ExperimentConfig:
    config = default_experiment_config()
    if args.output:
        config = config.model_copy(update={"output_root": Path(args.output).resolve()})
    if args.model or args.base_url or args.api_key_env:
        llm = config.llm.model_copy(update={
            "model": args.model or config.llm.model,
            "base_url": args.base_url or config.llm.base_url,
            "api_key_env": args.api_key_env or config.llm.api_key_env,
            "seed": args.seed,
        })
        config = config.model_copy(update={"llm": llm})
    return config


def cmd_tasks(args) -> int:
    config = _config(args)
    tasks = build_task_specs(config)
    path = experiment_output_root(config) / "tasks.json"
    write_tasks_file(path, tasks)
    print(f"wrote {len(tasks)} tasks -> {path}")
    return 0


def cmd_golden(args) -> int:
    config = _config(args)
    tasks = load_tasks(config) or build_task_specs(config)
    results = build_all_golden(tasks, config, limit=args.limit)
    atomic_write_json(experiment_output_root(config) / "golden_build_report.json", {
        "built": len(results),
        "ok": sum(1 for r in results if r.get("ok")),
    })
    return 0


def cmd_run(args) -> int:
    config = _config(args)
    tasks = load_tasks(config) or build_task_specs(config)
    if args.tasks:
        wanted = set(args.tasks.split(","))
        tasks = [t for t in tasks if t.task_id in wanted]
    method = MethodSpec(
        method_id=args.method_id,
        display_name=args.method_id,
        llm=config.llm,
        flags={"template": args.template,
               "agentic": args.agentic,
               "force_generative": not args.no_force_generative},
    )
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    results = run_benchmark(tasks, [method], seeds, config)
    summary_path = experiment_output_root(config) / "runs" / "run_summary.json"
    atomic_write_json(summary_path, {
        "completed": sum(1 for r in results if r.ok),
        "total": len(results),
        "failed": sum(1 for r in results if not r.ok),
    })
    return 0


def cmd_aggregate(args) -> int:
    config = _config(args)
    tasks = load_tasks(config) or build_task_specs(config)
    aggregate = aggregate_all(load_runs(config), tasks, method_id=args.method_id)
    path = experiment_output_root(config) / "aggregate.json"
    write_aggregate(path, aggregate)
    print(f"aggregate -> {path}")
    return 0


def cmd_report(args) -> int:
    config = _config(args)
    tasks = load_tasks(config) or build_task_specs(config)
    aggregate = aggregate_all(load_runs(config), tasks, method_id=args.method_id)
    stats = {}
    write_report(aggregate, stats, experiment_output_root(config) / "reports")
    return 0


def _suite_paths(config, suite: str):
    from .suites.base import suite_root
    root = suite_root(config, suite)
    return root


def cmd_regen(args) -> int:
    config = _config(args)
    from .aggregate import load_tasks
    from .suites import regen
    tasks = load_tasks(config)
    root = _suite_paths(config, "regen")
    perturbations = regen.build_tasks(config, seed=args.seed or 0)
    write_suite = root / "tasks.json"
    from .utils import atomic_write_json
    atomic_write_json(write_suite, perturbations)
    print(f"regen tasks -> {write_suite} ({len(perturbations)})")
    if args.run:
        results = regen.run_suite(tasks, perturbations, config)
        from .suites.base import write_collection
        paths = write_collection(root, "regen_800", "regen_v1", results,
                                 regen.aggregate(results), config=config, prefix="regen")
        print("collection ->", paths["manifest"])
    return 0


def cmd_infeasible(args) -> int:
    config = _config(args)
    from .aggregate import load_tasks
    from .suites import infeasible
    tasks = load_tasks(config)
    root = _suite_paths(config, "infeasible")
    infs = infeasible.build_tasks(tasks)
    from .utils import atomic_write_json
    atomic_write_json(root / "tasks.json", infs)
    print(f"infeasible tasks -> {root / 'tasks.json'} ({len(infs)})")
    if args.run:
        results = infeasible.run_suite(
            infs, config, with_constraints=not args.without_constraints)
        from .suites.base import write_collection
        paths = write_collection(root, "infeasible_120", "infeasible_v1", results,
                                 infeasible.aggregate(results), config=config,
                                 prefix="infeasible")
        print("collection ->", paths["manifest"])
    return 0


def cmd_semantics(args) -> int:
    config = _config(args)
    from .aggregate import load_tasks
    from .runner import run_task
    from .schemas import MethodSpec
    from .suites import semantics
    tasks = load_tasks(config)
    root = _suite_paths(config, "semantics")
    items = semantics.build_tasks(tasks)
    from .utils import atomic_write_json
    atomic_write_json(root / "tasks.json", items)
    print(f"semantic tasks -> {root / 'tasks.json'} ({len(items)})")
    if args.run:
        results = []
        for item in items:
            task = next(t for t in tasks if t.task_id == item["task_id"])
            spec = task.model_copy(update={"prompt": item["prompt"]})
            method = MethodSpec(method_id="semantics", display_name="semantics",
                                llm=config.llm)
            run = run_task(spec, method, seed=0, config=config)
            metrics = {m.metric_id: m.value for m in run.metrics}
            results.append({
                "semantic_id": item["semantic_id"], "category": item["category"],
                "param_consistent": metrics.get("parameter_extraction_accuracy") == 1.0,
                "fdg_isomorphic": bool(metrics.get("fdg_node_f1") == 1.0
                                       and metrics.get("fdg_edge_f1") == 1.0),
                "engineering_ok": run.ok,
            })
        atomic_write_json(root / "results.json", results)
        atomic_write_json(root / "aggregate.json", semantics.aggregate(results))
        from .suites.base import write_collection
        paths = write_collection(root, "semantics_320", "semantics_v1", results,
                                 semantics.aggregate(results), config=config,
                                 prefix="semantics")
        print("collection ->", paths["manifest"])
    return 0


def cmd_tools(args) -> int:
    config = _config(args)
    from .aggregate import load_tasks
    from .suites import tools
    tasks = load_tasks(config)
    root = _suite_paths(config, "tools")
    items = tools.build_tasks(tasks)
    from .utils import atomic_write_json
    atomic_write_json(root / "tasks.json", items)
    print(f"tool tasks -> {root / 'tasks.json'} ({len(items)})")
    if args.run:
        results = tools.run_suite(tasks, items, config, seeds=args.seeds)
        from .suites.base import write_collection
        paths = write_collection(root, "tools_160x5", "tool_v1", results,
                                 tools.aggregate(results), config=config, prefix="tool")
        print("collection ->", paths["manifest"])
    return 0


def cmd_methods(args) -> int:
    from .suites.methods import method_specs
    specs = method_specs(api_key_env=args.api_key_env or "DEEPSEEK_API_KEY")
    for spec in specs:
        print(f"{spec.method_id}: {spec.display_name} -> {spec.llm.model} "
              f"({spec.llm.base_url}, key env={spec.llm.api_key_env})")
    return 0


def cmd_direct(args) -> int:
    config = _config(args)
    from .aggregate import load_tasks
    from .suites import direct_base
    tasks = load_tasks(config)
    root = _suite_paths(config, "direct_base")
    from .utils import atomic_write_json
    seeds = tuple(int(s) for s in args.seeds.split(",") if s.strip())
    results = direct_base.run_suite(tasks, config, seeds=seeds)
    records = [r.model_dump(mode="json") for r in results]
    from .suites.base import stamp_record, write_collection
    records = [stamp_record(r, "direct", "direct_v1") for r in records]
    paths = write_collection(root, "direct_base_400", "direct_v1", records,
                             direct_base.aggregate(results), config=config,
                             prefix="direct")
    print("collection ->", paths["manifest"])
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="main_experiment")
    parser.add_argument("--output", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument("--seed", type=int, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p_tasks = sub.add_parser("tasks")
    p_tasks.set_defaults(func=cmd_tasks)

    p_golden = sub.add_parser("golden")
    p_golden.add_argument("--limit", type=int, default=None)
    p_golden.set_defaults(func=cmd_golden)

    p_run = sub.add_parser("run")
    p_run.add_argument("--method-id", default="benchmark")
    p_run.add_argument("--tasks", default=None)
    p_run.add_argument("--seeds", default="0,1,2,3,4,5,6,7,8,9")
    p_run.add_argument("--template", action="store_true")
    p_run.add_argument("--agentic", action="store_true",
                       help="使用当前 agentic_l2 多智能体生成（否则走基准单次 L2）")
    p_run.add_argument("--no-force-generative", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_agg = sub.add_parser("aggregate")
    p_agg.add_argument("--method-id", default=None)
    p_agg.set_defaults(func=cmd_aggregate)

    p_report = sub.add_parser("report")
    p_report.add_argument("--method-id", default=None)
    p_report.set_defaults(func=cmd_report)

    p_regen = sub.add_parser("regen")
    p_regen.add_argument("--run", action="store_true")
    p_regen.set_defaults(func=cmd_regen)

    p_inf = sub.add_parser("infeasible")
    p_inf.add_argument("--run", action="store_true")
    p_inf.add_argument("--without-constraints", action="store_true")
    p_inf.set_defaults(func=cmd_infeasible)

    p_sem = sub.add_parser("semantics")
    p_sem.add_argument("--run", action="store_true")
    p_sem.set_defaults(func=cmd_semantics)

    p_tools = sub.add_parser("tools")
    p_tools.add_argument("--run", action="store_true")
    p_tools.add_argument("--seeds", type=int, default=5)
    p_tools.set_defaults(func=cmd_tools)

    p_methods = sub.add_parser("methods")
    p_methods.set_defaults(func=cmd_methods)

    p_direct = sub.add_parser("direct")
    p_direct.add_argument("--seeds", default="0,1,2,3,4,5,6,7,8,9")
    p_direct.set_defaults(func=cmd_direct)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
