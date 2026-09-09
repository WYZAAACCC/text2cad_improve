"""Resume the remaining T31-T40 seed 0-5 runs after a pool worker failure.

Completed runs (metrics.json + ok run.json) are kept; missing ones are rerun.
"""

from __future__ import annotations

import json
import math
import multiprocessing
import statistics
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"
RUN_ROOT = OUT / "other_seeds_60_T31_T40"
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


def _load_record(task: dict, seed: int) -> dict:
    rd = RUN_ROOT / "runs" / "smoke_generation_fix" / task["task_id"] / f"seed_{seed}" / "latest"
    rec = {
        "task": task["task_id"], "seed": seed, "level": task["level"],
        "ok": False, "error_stage": None, "vol": None, "surf": None,
        "key": None, "step": None, "slot_haus_mm": None, "disc_haus_mm": None,
        "slot_n": None, "gold_slot_n": None, "disc_n": None, "gold_disc_n": None,
    }
    run_path = rd / "run.json"
    if not run_path.exists():
        return rec
    run = json.loads(run_path.read_text(encoding="utf-8"))
    rec["ok"] = bool(run.get("ok"))
    rec["error_stage"] = run.get("error_stage")
    if (rd / "metrics.json").exists():
        m = json.loads((rd / "metrics.json").read_text(encoding="utf-8"))
        vals = {x.get("metric_id"): x.get("value") for x in m}
        rec["vol"] = vals.get("volume_relative_error")
        rec["surf"] = vals.get("surface_relative_error")
        rec["key"] = vals.get("key_dimension_relative_error")
        rec["step"] = vals.get("step_roundtrip_ok")
    try:
        run_ir = json.loads((rd / "raw_fixed.json").read_text(encoding="utf-8"))
        gold_ir = json.loads((OUT / "golden" / task["task_id"] / "canonical_ir.json")
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


def _worker(job) -> dict:
    task_dict, method_dict, seed = job
    from _main_experiment.config import default_experiment_config
    from _main_experiment.runner import run_task
    from _main_experiment.schemas import MethodSpec, TaskSpec

    task = TaskSpec.model_validate(task_dict)
    method = MethodSpec.model_validate(method_dict)
    config = default_experiment_config().model_copy(update={
        "output_root": RUN_ROOT.resolve(),
        "llm": method.llm,
    })
    run_task(task, method, seed, config)
    return _load_record(task_dict, seed)


def main() -> None:
    tasks = {t["task_id"]: t for t in
             json.loads((OUT / "tasks.json").read_text(encoding="utf-8"))}
    targets = [(f"T{t:02d}", s) for t in range(31, 41) for s in range(6)]
    pending = []
    done = []
    for task_id, seed in targets:
        rec = _load_record(tasks[task_id], seed)
        if rec["ok"] and rec.get("vol") is not None:
            done.append(rec)
        else:
            pending.append((task_id, seed))

    if pending:
        from _main_experiment.config import default_experiment_config
        from _main_experiment.schemas import MethodSpec
        cfg = default_experiment_config().model_copy(update={
            "llm": default_experiment_config().llm.model_copy(update={
                "thinking": {"type": "disabled"},
            }),
        })
        method = MethodSpec(method_id="smoke_generation_fix",
                            display_name="smoke_generation_fix",
                            llm=cfg.llm,
                            flags={"agentic": True, "force_generative": True})
        md = method.model_dump(mode="json")
        jobs = [(tasks[t], md, s) for t, s in pending]
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=min(WORKERS, len(jobs)), maxtasksperchild=1) as pool:
            for i, rec in enumerate(pool.imap_unordered(_worker, jobs, chunksize=1), 1):
                done.append(rec)
                print(f"progress {i}/{len(jobs)} {rec['task']}:{rec['seed']} "
                      f"ok={rec['ok']} vol={rec['vol']} surf={rec['surf']} "
                      f"slot_haus={rec['slot_haus_mm']} disc_haus={rec['disc_haus_mm']}",
                      flush=True)

    done.sort(key=lambda r: (r["task"], r["seed"]))
    ok = sum(1 for r in done if r["ok"])
    ok_rows = [r for r in done if r["ok"]]
    by_level = {}
    for lv in ("L1", "L2", "L3", "L4"):
        sub = [r for r in done if r.get("level") == lv]
        by_level[lv] = {
            "n": len(sub), "ok": sum(1 for r in sub if r["ok"]),
            "rate": sum(1 for r in sub if r["ok"]) / len(sub) if sub else None,
        }
    summary = {
        "n": len(done), "ok": ok, "rate": ok / len(done) if done else None,
        "by_level": by_level,
        "vol_mean": statistics.fmean([r["vol"] for r in ok_rows if r["vol"] is not None]) if ok_rows else None,
        "surf_mean": statistics.fmean([r["surf"] for r in ok_rows if r["surf"] is not None]) if ok_rows else None,
        "key_mean": statistics.fmean([r["key"] for r in ok_rows if r["key"] is not None]) if ok_rows else None,
        "step_pass": sum(1 for r in ok_rows if r["step"] is True),
        "records": done,
    }
    (RUN_ROOT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "records"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
