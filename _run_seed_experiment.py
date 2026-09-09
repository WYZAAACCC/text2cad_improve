"""Run all 40 tasks with one seed using the current clean agentic pipeline."""

from __future__ import annotations

import json
import multiprocessing
import shutil
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"
SEED = 8
METHOD_ID = "full_agentic_seed8"
WORKERS = 10
EXP_ROOT = OUT / "seed_experiment" / f"seed_{SEED}"


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
    rec = {"task": task.task_id, "level": task.level.value, "ok": result.ok,
           "error_stage": result.error_stage,
           "vol": None, "surf": None, "key": None, "step": None, "haus": None}
    if (rd / "metrics.json").exists():
        m = json.loads((rd / "metrics.json").read_text(encoding="utf-8"))
        vals = {x.get("metric_id"): x.get("value") for x in m}
        rec["vol"] = vals.get("volume_relative_error")
        rec["surf"] = vals.get("surface_relative_error")
        rec["key"] = vals.get("key_dimension_relative_error")
        rec["step"] = vals.get("step_roundtrip_ok")
        rec["haus"] = vals.get("slot_hausdorff_normalized")
    return rec


def main() -> None:
    if EXP_ROOT.exists():
        shutil.rmtree(EXP_ROOT)
    EXP_ROOT.mkdir(parents=True, exist_ok=True)
    tasks = json.loads((OUT / "tasks.json").read_text(encoding="utf-8"))
    from _main_experiment.config import default_experiment_config
    from _main_experiment.schemas import MethodSpec
    cfg = default_experiment_config().model_copy(update={
        "llm": default_experiment_config().llm.model_copy(update={
            "thinking": {"type": "disabled"},
        }),
    })
    method = MethodSpec(method_id=METHOD_ID, display_name=METHOD_ID,
                        llm=cfg.llm, flags={"agentic": True, "force_generative": True})
    md = method.model_dump(mode="json")
    jobs = [(t, md, SEED, str(EXP_ROOT)) for t in tasks]
    ctx = multiprocessing.get_context("spawn")
    recs = []
    with ctx.Pool(processes=WORKERS, maxtasksperchild=1) as pool:
        for i, r in enumerate(pool.imap_unordered(_worker, jobs, chunksize=1), 1):
            recs.append(r)
            ok = sum(1 for x in recs if x["ok"])
            print(f"progress {i}/{len(jobs)} ok={ok} last={r['task']} ok={r['ok']} "
                  f"vol={r['vol']} surf={r['surf']}", flush=True)
    ok = sum(1 for r in recs if r["ok"])
    ok_rows = [r for r in recs if r["ok"]]
    by_level = {}
    for lv in ("L1", "L2", "L3", "L4"):
        sub = [r for r in recs if r["level"] == lv]
        by_level[lv] = {"n": len(sub), "ok": sum(1 for r in sub if r["ok"]),
                        "rate": sum(1 for r in sub if r["ok"]) / len(sub) if sub else None}
    geom = {
        "n_ok": len(ok_rows),
        "vol_mean": statistics.fmean([r["vol"] for r in ok_rows if r["vol"] is not None]) if ok_rows else None,
        "surf_mean": statistics.fmean([r["surf"] for r in ok_rows if r["surf"] is not None]) if ok_rows else None,
        "key_mean": statistics.fmean([r["key"] for r in ok_rows if r["key"] is not None]) if ok_rows else None,
        "step_pass": sum(1 for r in ok_rows if r["step"] is True),
        "haus_mean": statistics.fmean([r["haus"] for r in ok_rows if r["haus"] is not None]) if ok_rows else None,
    }
    summary = {
        "seed": SEED, "method": METHOD_ID, "n": len(recs), "ok": ok,
        "rate": ok / len(recs) if recs else None,
        "by_level": by_level, "geometry": geom,
        "fail_stage": dict(Counter(r["error_stage"] for r in recs if not r["ok"])),
        "records": sorted(recs, key=lambda x: x["task"]),
    }
    (EXP_ROOT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# seed {SEED} 全 40 任务重跑",
        f"- 成功 {ok}/{len(recs)}（{ok / len(recs) * 100:.1f}%）",
        f"- 体积均值 {geom['vol_mean']}%，表面积均值 {geom['surf_mean']}%，"
        f"关键尺寸 {geom['key_mean']}%，STEP 回读 {geom['step_pass']}/{len(ok_rows)}",
        "",
        "## 按难度",
    ]
    for lv in ("L1", "L2", "L3", "L4"):
        b = by_level[lv]
        lines.append(f"| {lv} | {b['n']} | {b['ok']} | {b['rate'] * 100:.1f}% |")
    (EXP_ROOT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
