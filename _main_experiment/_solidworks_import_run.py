"""Commercial CAD (SolidWorks) independent STEP import experiment.

Samples 80 successful runs, imports their STEP files in SolidWorks, and
checks whether each imports as exactly one body (direct-import success).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import time


def _resolve_step(task: str, seed: int) -> pathlib.Path | None:
    out = pathlib.Path(__file__).resolve().parents[0] / "output"
    candidates = [
        out / f"replay_t14_with_llm/{task}/seed_{seed}/output.step",
        out / f"replay_t15_t24_with_llm/{task}/seed_{seed}/output.step",
        out / f"replay_with_llm/{task}/seed_{seed}/output.step",
        out / f"runs/full_agentic/{task}/seed_{seed}/latest/output.step",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--limit", type=int, default=None, help="冒烟：只跑前 N 个")
    args = parser.parse_args(argv)

    out = pathlib.Path(__file__).resolve().parents[0] / "output"
    final = json.loads(
        (out / "final_400_summary_latest.json").read_text(encoding="utf-8"))
    ok_runs = [(r["task"], r["seed"]) for r in final["rows"] if r["ok"]]
    rng = random.Random(args.seed)
    sample = rng.sample(ok_runs, min(args.sample, len(ok_runs)))
    if args.limit:
        sample = sample[: args.limit]

    records_dir = out / "_solidworks_import"
    records_dir.mkdir(parents=True, exist_ok=True)
    results_path = records_dir / "import_records.jsonl"
    done = set()
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    done.add(json.loads(line)["sample_id"])
                except Exception:
                    continue
    pending = []
    for idx, (task, seed) in enumerate(sample):
        sid = f"SW_IMP_{idx:03d}"
        if sid in done:
            continue
        step = _resolve_step(task, seed)
        pending.append({"sample_id": sid, "task": task, "seed": seed, "step": step})

    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
    client = SolidWorksClient(visible=False)
    started = time.monotonic()
    for i, rec in enumerate(pending, 1):
        t0 = time.monotonic()
        if rec["step"] is None:
            result = {"sample_id": rec["sample_id"], "task": rec["task"],
                      "seed": rec["seed"], "ok": False, "body_count": None,
                      "step": None, "error": "STEP file not found"}
        else:
            try:
                result = client.import_step_and_count_bodies(rec["step"], timeout=300)
                result.update({"sample_id": rec["sample_id"],
                               "task": rec["task"], "seed": rec["seed"]})
            except Exception as exc:  # noqa: BLE001
                result = {"sample_id": rec["sample_id"], "task": rec["task"],
                          "seed": rec["seed"], "ok": False, "body_count": None,
                          "step": str(rec["step"]), "error": str(exc)[:200]}
        result["collected_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        result["elapsed_s"] = round(time.monotonic() - t0, 2)
        with results_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(f"{result['sample_id']} {result['task']} seed={result['seed']} "
              f"bodies={result.get('body_count')} ok={result.get('ok')} "
              f"elapsed={result['elapsed_s']}s", flush=True)
    print(f"batch done: {len(pending)} runs, elapsed={time.monotonic()-started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
