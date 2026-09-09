"""Smoke test for the generation-side fixes (complex rim + exact fir-tree slot).

Runs a small task/seed subset through the full agentic pipeline and reports
success rate, geometry metrics, and contour-level Hausdorff distances against
the golden IR. Output is written to a dedicated directory and never touches
the main experiment runs.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import shutil
import statistics
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"
SMOKE_ROOT = OUT / "smoke_generation_fix"
WORKERS = 10


def _points_by_kind(ir: dict, kind: str) -> list:
    comp_kinds = {c.get("id"): c.get("kind_hint") for c in ir.get("components", [])}
    for node in ir.get("nodes", []):
        if node.get("op") != "add_polyline":
            continue
        nid = str(node.get("id", ""))
        cid = str(node.get("component", ""))
        kh = str(comp_kinds.get(node.get("component")) or "")
        if kind == "disc":
            matched = ("disc" in kh or "disc" in cid or "disc" in nid)
        else:
            matched = ("fir_tree" in kh or "slot" in kh or "cutter" in cid
                       or "slot" in cid or "cutter" in nid or "slot" in nid)
        if matched:
            points = (node.get("params") or {}).get("points") or []
            if points:
                return [(float(p["x_mm"]), float(p["y_mm"])) for p in points]
    return []


def _hausdorff(a: list, b: list) -> float:
    if not a or not b:
        return float("inf")

    def one(x, y):
        return max(min(math.dist(px, py) for py in y) for px in x)

    return max(one(a, b), one(b, a))


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
        "task": task.task_id, "seed": seed, "level": task.level.value,
        "ok": result.ok,
        "error_stage": result.error_stage, "vol": None, "surf": None,
        "key": None, "step": None, "slot_haus_mm": None, "disc_haus_mm": None,
        "slot_n": None, "gold_slot_n": None, "disc_n": None, "gold_disc_n": None,
    }
    if (rd / "metrics.json").exists():
        m = json.loads((rd / "metrics.json").read_text(encoding="utf-8"))
        vals = {x.get("metric_id"): x.get("value") for x in m}
        rec["vol"] = vals.get("volume_relative_error")
        rec["surf"] = vals.get("surface_relative_error")
        rec["key"] = vals.get("key_dimension_relative_error")
        rec["step"] = vals.get("step_roundtrip_ok")
    try:
        run_ir = json.loads((rd / "raw_fixed.json").read_text(encoding="utf-8"))
        gold_ir = json.loads((OUT / "golden" / task.task_id / "canonical_ir.json")
                             .read_text(encoding="utf-8"))
        run_disc, gold_disc = _points_by_kind(run_ir, "disc"), _points_by_kind(gold_ir, "disc")
        run_slot, gold_slot = _points_by_kind(run_ir, "slot"), _points_by_kind(gold_ir, "slot")
        rec["disc_n"], rec["gold_disc_n"] = len(run_disc), len(gold_disc)
        rec["slot_n"], rec["gold_slot_n"] = len(run_slot), len(gold_slot)
        if run_disc and gold_disc:
            rec["disc_haus_mm"] = round(_hausdorff(run_disc, gold_disc), 3)
        if run_slot and gold_slot:
            rec["slot_haus_mm"] = round(_hausdorff(run_slot, gold_slot), 3)
    except Exception:
        pass
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True,
                    help="comma-separated Txx:seed entries, e.g. T33:0,T20:8")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--out", default=None,
                    help="output directory under _main_experiment/output (default smoke_generation_fix)")
    args = ap.parse_args()

    targets = []
    for item in args.tasks.split(","):
        item = item.strip()
        if not item:
            continue
        task_id, seed = item.split(":")
        targets.append((task_id.strip(), int(seed)))

    root = OUT / (args.out or "smoke_generation_fix")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    tasks = {t["task_id"]: t for t in
             json.loads((OUT / "tasks.json").read_text(encoding="utf-8"))}
    from _main_experiment.config import default_experiment_config
    from _main_experiment.schemas import MethodSpec

    cfg = default_experiment_config().model_copy(update={
        "llm": default_experiment_config().llm.model_copy(update={
            "thinking": {"type": "disabled"},
        }),
    })
    method = MethodSpec(method_id="smoke_generation_fix", display_name="smoke_generation_fix",
                        llm=cfg.llm, flags={"agentic": True, "force_generative": True})
    md = method.model_dump(mode="json")
    jobs = [(tasks[t], md, s, str(root)) for t, s in targets]

    ctx = multiprocessing.get_context("spawn")
    recs = []
    with ctx.Pool(processes=min(args.workers, len(jobs)), maxtasksperchild=1) as pool:
        for i, r in enumerate(pool.imap_unordered(_worker, jobs, chunksize=1), 1):
            recs.append(r)
            print(f"progress {i}/{len(jobs)} {r['task']}:{r['seed']} ok={r['ok']} "
                  f"vol={r['vol']} surf={r['surf']} slot_haus={r['slot_haus_mm']} "
                  f"disc_haus={r['disc_haus_mm']}", flush=True)

    recs.sort(key=lambda r: (r["task"], r["seed"]))
    ok = sum(1 for r in recs if r["ok"])
    ok_rows = [r for r in recs if r["ok"]]
    by_level = {}
    for lv in ("L1", "L2", "L3", "L4"):
        sub = [r for r in recs if r.get("level") == lv]
        by_level[lv] = {
            "n": len(sub),
            "ok": sum(1 for r in sub if r["ok"]),
            "rate": sum(1 for r in sub if r["ok"]) / len(sub) if sub else None,
        }
    summary = {
        "n": len(recs), "ok": ok, "rate": ok / len(recs) if recs else None,
        "by_level": by_level,
        "vol_mean": statistics.fmean([r["vol"] for r in ok_rows if r["vol"] is not None]) if ok_rows else None,
        "surf_mean": statistics.fmean([r["surf"] for r in ok_rows if r["surf"] is not None]) if ok_rows else None,
        "key_mean": statistics.fmean([r["key"] for r in ok_rows if r["key"] is not None]) if ok_rows else None,
        "step_pass": sum(1 for r in ok_rows if r["step"] is True),
        "records": recs,
    }
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
