"""Parallel runner for the tool-planning suite (fixed / MCP agent / LLM code)."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import pathlib
import time


def _run_one(payload: dict) -> dict:
    from _main_experiment.aggregate import load_tasks
    from _main_experiment.config import default_experiment_config
    from _main_experiment.llm import OpenAICompatToolClient
    from _main_experiment.suites import tools
    from _main_experiment.suites.base import ensure_golden

    config = default_experiment_config()
    config = config.model_copy(update={
        "llm": config.llm.model_copy(update={"thinking": {"type": "disabled"}}),
    })
    task = next(t for t in load_tasks(config)
                if t.task_id == payload["task_id"])
    base_dir = str(ensure_golden(task, config))
    tool_task = payload["tool_task"]
    interface = payload["interface"]
    seed = payload["seed"]
    llm = config.llm.model_copy(update={"seed": seed})
    client = OpenAICompatToolClient()
    try:
        if interface == "fixed":
            rec = tools._run_fixed(tool_task, base_dir)
        elif interface == "mcp_agent":
            rec = tools._run_mcp_agent(tool_task, base_dir, client, llm)
        else:
            rec = tools._run_llm_code(tool_task, base_dir, client, llm)
    except Exception as exc:  # noqa: BLE001
        rec = {"tool_task_id": tool_task.get("tool_task_id"),
               "category": tool_task.get("category"),
               "selected": set(), "expected": set(tool_task.get("tool_sequence", [])),
               "binding_ok": False, "multi_complete": False,
               "result_ok": False, "new_tool_called": False,
               "error": str(exc)[:200]}
    rec["interface"] = interface
    rec["seed"] = seed
    for key in ("selected", "expected"):
        if isinstance(rec.get(key), set):
            rec[key] = sorted(rec[key])
    return rec


def _read_done(results_path: pathlib.Path) -> set[str]:
    if not results_path.exists():
        return set()
    done: set[str] = set()
    for line in results_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            done.add(f"{r['tool_task_id']}|{r['interface']}|{r['seed']}")
        except Exception:
            continue
    return done


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--category", default=None)
    parser.add_argument("--interface", default=None,
                        choices=["fixed", "mcp_agent", "llm_code"])
    parser.add_argument("--tasks-limit", type=int, default=None)
    parser.add_argument("--seeds", default="0,1,2,3,4")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args(argv)

    from _main_experiment.config import default_experiment_config
    from _main_experiment.suites import tools
    from _main_experiment.suites.base import write_collection

    config = default_experiment_config()
    items = json.loads(
        (config.resolved_output_root() / "suites" / "tools" / "tasks.json")
        .read_text(encoding="utf-8"))
    if args.category:
        items = [i for i in items if i["category"] == args.category]
    if args.tasks_limit:
        items = items[: args.tasks_limit]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    interfaces = ["fixed", "mcp_agent", "llm_code"] if not args.interface \
        else [args.interface]

    jobs = []
    for item in items:
        for interface in interfaces:
            for seed in seeds:
                jobs.append({"tool_task": item, "task_id": item["task_id"],
                             "interface": interface, "seed": seed})

    results_path = (config.resolved_output_root() / "suites" / "tools"
                    / "tools_results.jsonl")
    done = set() if args.no_resume else _read_done(results_path)
    pending = [j for j in jobs
               if f"{j['tool_task']['tool_task_id']}|{j['interface']}|{j['seed']}"
               not in done]
    print(f"jobs={len(jobs)} done={len(jobs) - len(pending)} "
          f"pending={len(pending)} workers={args.workers}", flush=True)
    if not pending:
        print("nothing to run", flush=True)
    else:
        started = time.monotonic()
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=args.workers, maxtasksperchild=8) as pool:
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
    agg_records = []
    for r in records:
        r2 = dict(r)
        r2["selected"] = set(r.get("selected") or [])
        r2["expected"] = set(r.get("expected") or [])
        agg_records.append(r2)
    aggregate = tools.aggregate(agg_records)
    root = config.resolved_output_root() / "suites" / "tools"
    paths = write_collection(root, "tools_160x5", "tool_v1", records,
                             aggregate, config=config, prefix="tool")
    print("collection ->", paths["manifest"], flush=True)
    print("aggregate:", json.dumps(aggregate, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
