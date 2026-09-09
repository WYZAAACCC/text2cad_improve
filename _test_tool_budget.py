"""Test slot contour generation with raised tool-call budget (6 calls)."""

from __future__ import annotations

import json
import math
import multiprocessing
import shutil
import sys
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"
TEST_ROOT = OUT / "tool_budget_test"
sys.path.insert(0, str(ROOT))

TARGETS = [
    ("T20", 5), ("T21", 1), ("T22", 1), ("T23", 2),
    ("T33", 1), ("T34", 0), ("T19", 0),
]


def _worker(job) -> dict:
    task_dict, method_dict, seed, tmp_root = job
    from _main_experiment.config import default_experiment_config
    from _main_experiment.runner import run_task
    from _main_experiment.schemas import MethodSpec, TaskSpec

    task = TaskSpec.model_validate(task_dict)
    method = MethodSpec.model_validate(method_dict)
    config = default_experiment_config().model_copy(update={
        "output_root": Path(tmp_root).resolve(),
        "llm": method.llm,
    })
    result = run_task(task, method, seed, config)
    rd = Path(tmp_root) / "runs" / method.method_id / task.task_id / f"seed_{seed}" / "latest"
    rec = {
        "task": task.task_id, "seed": seed, "ok": result.ok,
        "error_stage": result.error_stage, "vol": None, "surf": None,
        "slot_hausdorff": None, "slot_n": None, "gold_n": None,
    }
    if (rd / "metrics.json").exists():
        m = json.loads((rd / "metrics.json").read_text(encoding="utf-8"))
        vals = {x.get("metric_id"): x.get("value") for x in m}
        rec["vol"] = vals.get("volume_relative_error")
        rec["surf"] = vals.get("surface_relative_error")
    try:
        run_doc = json.loads((rd / "canonical_ir.json").read_text(encoding="utf-8"))
        gold_doc = json.loads((OUT / "golden" / task.task_id / "canonical_ir.json").read_text(encoding="utf-8"))
        def pts(doc):
            for n in doc.get("nodes", []):
                if n.get("op") != "add_polyline":
                    continue
                nid = str(n.get("id", "")); comp = str(n.get("component", ""))
                if "cutter" in nid or "cutter" in comp or "slot" in nid:
                    return [(float(p["x_mm"]), float(p["y_mm"]))
                            for p in (n.get("params") or {}).get("points", [])]
            return []
        rp, gp = pts(run_doc), pts(gold_doc)
        rec["slot_n"], rec["gold_n"] = len(rp), len(gp)
        if rp and gp:
            def haus(a, b):
                def one(x, y):
                    return max(min(math.dist(px, py) for py in y) for px in x)
                return max(one(a, b), one(b, a))
            rec["slot_hausdorff"] = round(haus(rp, gp), 3)
    except Exception:
        pass
    return rec


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=None)
    args = ap.parse_args()
    targets = TARGETS
    if args.tasks:
        targets = []
        for item in args.tasks.split(","):
            t, s = item.strip().split(":")
            targets.append((t, int(s)))
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    tasks = json.loads((OUT / "tasks.json").read_text(encoding="utf-8"))
    tasks = {t["task_id"]: t for t in tasks}
    from _main_experiment.config import default_experiment_config
    from _main_experiment.schemas import MethodSpec
    cfg = default_experiment_config().model_copy(update={
        "llm": default_experiment_config().llm.model_copy(update={
            "thinking": {"type": "disabled"},
        }),
    })
    method = MethodSpec(method_id="tool_budget_test", display_name="tool_budget_test",
                        llm=cfg.llm, flags={"agentic": True, "force_generative": True})
    md = method.model_dump(mode="json")
    jobs = []
    for task, seed in targets:
        jobs.append((tasks[task], md, seed, str(TEST_ROOT)))
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=len(jobs), maxtasksperchild=1) as pool:
        for r in pool.imap_unordered(_worker, jobs, chunksize=1):
            print(r, flush=True)
    (TEST_ROOT / "test_report.json").write_text(
        json.dumps(TARGETS, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
