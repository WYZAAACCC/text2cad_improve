"""Parallel main-experiment runner.

Uses multiprocessing.Pool (spawn) with per-task process isolation so an OCP/CAD
crash in one run cannot corrupt other runs. Supports resume and auto worker
count based on CPU/RAM.

Usage (repo root):
  python -m _main_experiment.parallel_run --method-id full_agentic --agentic
"""
from __future__ import annotations

import argparse
import ctypes
import json
import multiprocessing
import os
import time
from pathlib import Path
from typing import Any


def _auto_workers() -> int:
    logical = os.cpu_count() or 4
    try:

        class _MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = _MemoryStatus()
        stat.dwLength = ctypes.sizeof(_MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        avail_gb = stat.ullAvailPhys / (1024 ** 3)
        ram_limit = max(2, int(avail_gb // 1.5))
    except Exception:  # noqa: BLE001
        ram_limit = 6
    return max(1, min(logical // 2, ram_limit, 12))


def _worker(job: tuple[dict[str, Any], dict[str, Any], int, str | None, float]) -> dict[str, Any]:
    """Run one benchmark task in a fresh process and return a summary record."""
    task_dict, method_dict, seed, output_root, delay = job
    if delay > 0:
        time.sleep(delay)
    from .config import default_experiment_config
    from .paths import run_dir
    from .runner import run_task
    from .schemas import MethodSpec, TaskSpec

    task = TaskSpec.model_validate(task_dict)
    method = MethodSpec.model_validate(method_dict)
    config = default_experiment_config()
    if output_root:
        config = config.model_copy(update={
            "output_root": Path(output_root).resolve(),
            "llm": method.llm,
        })
    else:
        config = config.model_copy(update={"llm": method.llm})
    if method_dict.get("flags", {}).get("direct_base"):
        from .suites.direct_base import run_direct_base
        result = run_direct_base(task, config, seed)
    else:
        result = run_task(task, method, seed, config)
    return {
        "run_id": result.run_id,
        "method_id": result.method_id,
        "task_id": result.task_id,
        "seed": result.seed,
        "status": result.status.value,
        "ok": result.ok,
        "record_id": result.record_id,
        "collected_at": result.collected_at,
        "error_stage": result.error_stage,
        "error_message": (result.error_message or "")[:300],
    }


def _completed_ids(output_root: Path) -> set[tuple[str, str, int]]:
    completed: set[tuple[str, str, int]] = set()
    for run_file in (output_root / "runs").rglob("run.json"):
        if "seed_" not in str(run_file):
            continue
        try:
            data = json.loads(run_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if data.get("status") == "completed":
            completed.add((data.get("method_id", ""), data.get("task_id", ""),
                           int(data.get("seed", -1))))
    return completed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--method-id", default="full_agentic")
    parser.add_argument("--agentic", action="store_true",
                        help="使用当前 agentic_l2 多智能体生成")
    parser.add_argument("--template", action="store_true",
                        help="模板基线（不调 LLM），用于脚本自检")
    parser.add_argument("--tasks", default=None,
                        help="逗号分隔任务子集，如 T01,T02")
    parser.add_argument("--seeds", default="0,1,2,3,4,5,6,7,8,9")
    parser.add_argument("--workers", type=int, default=None,
                        help="并行进程数（默认按 CPU/RAM 自动）")
    parser.add_argument("--output", default=None)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--model", default=None, help="LLM model override")
    parser.add_argument("--base-url", default=None, help="LLM base URL override")
    parser.add_argument("--api-key-env", default=None, help="LLM API key env var override")
    parser.add_argument("--tool-choice", default=None, help="LLM tool_choice override (required/auto/none)")
    parser.add_argument("--max-tokens", type=int, default=None, help="LLM max_tokens override")
    parser.add_argument("--stagger-seconds", type=float, default=0.0, help="stagger task start by N seconds each")
    parser.add_argument("--thinking", default=None, help="LLM thinking extra_body as JSON dict")
    parser.add_argument("--ablation", default=None,
                        choices=["direct_base", "single_agent", "multi_no_repair",
                                 "multi_inner", "full"],
                        help="消融架构：direct_base / single_agent / multi_no_repair / "
                             "multi_inner / full")
    args = parser.parse_args(argv)

    from .aggregate import load_tasks
    from .config import default_experiment_config
    from .schemas import MethodSpec
    from .utils import atomic_write_json

    config = default_experiment_config()
    if args.model or args.base_url or args.api_key_env or args.tool_choice or args.max_tokens is not None or args.thinking is not None:
        config = config.model_copy(update={"llm": config.llm.model_copy(update={
            "model": args.model or config.llm.model,
            "base_url": args.base_url or config.llm.base_url,
            "api_key_env": args.api_key_env or config.llm.api_key_env,
            "tool_choice": args.tool_choice or config.llm.tool_choice,
            "max_tokens": args.max_tokens if args.max_tokens is not None else config.llm.max_tokens,
            "thinking": json.loads(args.thinking) if args.thinking is not None else config.llm.thinking,
        })})
    if args.output:
        config = config.model_copy(update={"output_root": Path(args.output).resolve()})
    output_root = config.resolved_output_root()
    tasks_config = config
    if not (config.resolved_output_root() / "tasks.json").exists():
        tasks_config = default_experiment_config()
    tasks = load_tasks(tasks_config)
    if args.tasks:
        wanted = set(args.tasks.split(","))
        tasks = [t for t in tasks if t.task_id in wanted]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    if args.ablation:
        method_id = f"ablation_{args.ablation}"
        flags: dict[str, Any] = {"force_generative": True}
        if args.ablation == "direct_base":
            flags.update({"direct_base": True, "agentic": False})
        elif args.ablation == "single_agent":
            flags.update({"agentic": False, "repair_enabled": True,
                          "deterministic_autofix_enabled": True})
        elif args.ablation == "multi_no_repair":
            flags.update({"agentic": True, "repair_enabled": False,
                          "deterministic_autofix_enabled": False})
        elif args.ablation == "multi_inner":
            flags.update({"agentic": True, "repair_enabled": True,
                          "deterministic_autofix_enabled": True})
        elif args.ablation == "full":
            flags.update({"agentic": True, "repair_enabled": True,
                          "deterministic_autofix_enabled": True,
                          "outer_feedback_repair": True})
        method = MethodSpec(
            method_id=method_id,
            display_name=method_id,
            llm=config.llm,
            flags=flags,
        )
    else:
        method = MethodSpec(
            method_id=args.method_id,
            display_name=args.method_id,
            llm=config.llm,
            flags={"template": args.template, "agentic": args.agentic,
                   "force_generative": True},
        )
    workers = args.workers or _auto_workers()

    jobs: list[tuple[dict[str, Any], dict[str, Any], int, str | None, float]] = []
    for idx, task in enumerate(tasks):
        for seed in seeds:
            jobs.append((task.model_dump(mode="json"), method.model_dump(mode="json"),
                         seed, str(output_root), args.stagger_seconds * idx))
    if not args.no_resume:
        completed = _completed_ids(output_root)
        before = len(jobs)
        jobs = [j for j in jobs if (j[1].get("method_id"), j[0].get("task_id"), j[2])
                not in completed]
        print(f"resume: {before} jobs, {len(jobs)} pending")
    else:
        print(f"jobs: {len(jobs)}")

    done: list[dict[str, Any]] = []
    pending = jobs
    attempts = 0
    while pending and attempts < 10:
        attempts += 1
        print(f"[round {attempts}] running {len(pending)} jobs with {workers} workers")
        ctx = multiprocessing.get_context("spawn")
        try:
            with ctx.Pool(processes=workers, maxtasksperchild=1) as pool:
                for i, summary in enumerate(pool.imap_unordered(_worker, pending, chunksize=1), 1):
                    done.append(summary)
                    if i % 10 == 0 or i == len(pending):
                        ok = sum(1 for d in done if d.get("ok"))
                        print(f"  progress {i}/{len(pending)} ok={ok}")
            pending = []
        except Exception as exc:  # noqa: BLE001
            print(f"  worker crash detected: {type(exc).__name__}: {str(exc)[:160]}")
            completed = _completed_ids(output_root)
            done_ids = {(d["method_id"], d["task_id"], d["seed"]) for d in done}
            pending = [
                j for j in pending
                if (j[1].get("method_id"), j[0].get("task_id"), j[2]) not in completed
                and (j[1].get("method_id"), j[0].get("task_id"), j[2]) not in done_ids
            ]
            print(f"  retrying {len(pending)} remaining")

    summary_path = output_root / "runs" / "run_summary_parallel.json"
    atomic_write_json(summary_path, {
        "schema_version": "parallel_summary_v1",
        "method_id": args.method_id,
        "workers": workers,
        "jobs": len(jobs),
        "completed": sum(1 for d in done if d.get("ok")),
        "failed": sum(1 for d in done if not d.get("ok")),
        "records": done,
    })
    print(f"summary -> {summary_path}")
    print(f"total={len(done)} ok={sum(1 for d in done if d.get('ok'))} "
          f"failed={sum(1 for d in done if not d.get('ok'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
