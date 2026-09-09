"""Recompute all paper-required metrics from raw experiment records.

This script is read-only: it only reads run outputs and writes one JSON
summary (paper_metrics_all.json) plus a human-readable Markdown table block.
The authoritative success rows for the merged 400-run main experiment come
from final_400_summary_latest.json; all other values are derived from the
raw run/repair/metrics records referenced by those rows.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"
TASKS_JSON = OUT / "tasks.json"
FINAL_400 = OUT / "final_400_summary_latest.json"
FULL_AGENTIC = OUT / "runs" / "full_agentic"


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def metric(m, mid):
    if not m:
        return None
    for x in m:
        if x.get("metric_id") == mid:
            return x
    return None


def fmt_pct(x, nd=1):
    if x is None:
        return "N/A"
    return f"{x * 100:.{nd}f}"


# ---------------------------------------------------------------------------
# task metadata
# ---------------------------------------------------------------------------
tasks = load_json(TASKS_JSON, [])
task_meta = {}
for t in tasks:
    task_meta[t["task_id"]] = {
        "level": t.get("level"),
        "slot": (t.get("gold") or {}).get("slot_reference") is not None,
        "family_id": t.get("family_id"),
    }


# ---------------------------------------------------------------------------
# merged 400 rows
# ---------------------------------------------------------------------------
def merged_run_dir(task: str, seed: int) -> Path:
    base = OUT
    if task == "T14":
        return base / "replay_t14_with_llm" / task / f"seed_{seed}"
    if "T15" <= task <= "T24":
        return base / "replay_t15_t24_with_llm" / task / f"seed_{seed}"
    if "T25" <= task <= "T31":
        return base / "replay_with_llm" / task / f"seed_{seed}"
    if task == "T32" and seed <= 2:
        return base / "replay_with_llm" / task / f"seed_{seed}"
    return FULL_AGENTIC / task / f"seed_{seed}" / "latest"


def load_repair_summary(run_dir: Path):
    d = load_json(run_dir / "repair_summary.json", {})
    outcome = d.get("outcome", {})
    return {
        "ok": outcome.get("ok"),
        "stop_code": outcome.get("stop_code"),
        "stop_reason": outcome.get("stop_reason"),
        "autofix_accepted": outcome.get("autofix_accepted"),
        "validation_llm_attempts": outcome.get("validation_llm_attempts", 0) or 0,
        "runtime_llm_attempts": outcome.get("runtime_llm_attempts", 0) or 0,
        "accepted_patches": outcome.get("accepted_patches", []) or [],
        "rejected_patches": outcome.get("rejected_patches", []) or [],
    }


def load_run(run_dir: Path):
    d = load_json(run_dir / "run.json", {})
    return {
        "ok": d.get("ok"),
        "repair_rounds": d.get("repair_rounds"),
        "attempts_used": d.get("attempts_used"),
        "error_stage": d.get("error_stage"),
        "error_code": d.get("error_code"),
        "error_message": d.get("error_message"),
        "usage": d.get("usage"),
        "collected_at": d.get("collected_at"),
    }


def load_metrics(run_dir: Path):
    m = load_json(run_dir / "metrics.json", [])
    if not isinstance(m, list):
        return {}
    out = {}
    for mid in (
        "parameter_accuracy",
        "parameter_extraction_accuracy",
        "fdg_node_f1",
        "fdg_edge_f1",
        "first_validation_pass",
        "key_dimension_relative_error",
        "volume_relative_error",
        "surface_relative_error",
        "step_roundtrip_ok",
        "slot_hausdorff_normalized",
        "repair_rounds",
        "failure_category",
        "regeneration_ok",
        "regeneration_skipped",
        "geometry_skipped",
    ):
        x = metric(m, mid)
        if x is not None:
            out[mid] = x.get("value")
            if x.get("notes"):
                out[mid + "_notes"] = x.get("notes")
    return out


final_rows = load_json(FINAL_400, {}).get("rows", [])
merged = []
for r in final_rows:
    task = r["task"]
    seed = int(r["seed"])
    run_dir = merged_run_dir(task, seed)
    rep = load_repair_summary(run_dir)
    run = load_run(run_dir)
    met = load_metrics(run_dir)
    merged.append(
        {
            "task": task,
            "seed": seed,
            "level": task_meta.get(task, {}).get("level"),
            "slot": task_meta.get(task, {}).get("slot", False),
            "ok": bool(r["ok"]),
            "repair": rep,
            "run": run,
            "metrics": met,
        }
    )


def mean(vals):
    vals = [v for v in vals if v is not None]
    return statistics.fmean(vals) if vals else None


def pct(vals):
    vals = [v for v in vals if v is not None]
    return mean(vals)


def summarize_main(rows):
    groups = {
        "overall": rows,
        "L1": [r for r in rows if r["level"] == "L1"],
        "L2": [r for r in rows if r["level"] == "L2"],
        "L3": [r for r in rows if r["level"] == "L3"],
        "L4": [r for r in rows if r["level"] == "L4"],
        "slot": [r for r in rows if r["slot"]],
        "no_slot": [r for r in rows if not r["slot"]],
    }
    summary = {}
    for name, sub in groups.items():
        n = len(sub)
        ok = sum(1 for r in sub if r["ok"])
        llm_att = [r["repair"]["validation_llm_attempts"] + r["repair"]["runtime_llm_attempts"] for r in sub]
        pass1 = sum(1 for r in sub if r["ok"] and (r["repair"]["validation_llm_attempts"] + r["repair"]["runtime_llm_attempts"]) == 0)
        key_err = [r["metrics"]["key_dimension_relative_error"] for r in sub if r["ok"] and r["metrics"].get("key_dimension_relative_error") is not None]
        repair_rounds_run = [r["run"]["repair_rounds"] for r in sub if r["run"]["repair_rounds"] is not None]
        summary[name] = {
            "n": n,
            "ok": ok,
            "final_rate": ok / n if n else None,
            "pass1": pass1,
            "pass1_rate": pass1 / n if n else None,
            "avg_llm_repair_all": mean(llm_att),
            "avg_llm_repair_success": mean(
                [v for r, v in zip(sub, llm_att) if r["ok"]]
            ),
            "avg_total_repair_rounds": mean(repair_rounds_run),
            "repair_rounds_coverage": len(repair_rounds_run),
            "avg_key_dim_error": mean(key_err),
            "key_dim_error_n": len(key_err),
            "repair_round_dist": dict(
                Counter(
                    min(3, r["repair"]["validation_llm_attempts"] + r["repair"]["runtime_llm_attempts"])
                    for r in sub
                    if r["ok"] and (r["repair"]["validation_llm_attempts"] + r["repair"]["runtime_llm_attempts"]) > 0
                )
            ),
        }
    return summary


main_summary = summarize_main(merged)


def summarize_model(records):
    rows = list(records.values())
    n = len(rows)
    ok = sum(1 for r in rows if r["run"]["ok"])
    pass1 = sum(
        1
        for r in rows
        if r["run"]["ok"]
        and (r["repair"]["validation_llm_attempts"] + r["repair"]["runtime_llm_attempts"]) == 0
    )
    param_all = [r["metrics"]["parameter_extraction_accuracy"] for r in rows if r["metrics"].get("parameter_extraction_accuracy") is not None]
    fdg_node_all = [r["metrics"]["fdg_node_f1"] for r in rows if r["metrics"].get("fdg_node_f1") is not None]
    fdg_edge_all = [r["metrics"]["fdg_edge_f1"] for r in rows if r["metrics"].get("fdg_edge_f1") is not None]
    first_val_all = [r["metrics"]["first_validation_pass"] for r in rows if r["metrics"].get("first_validation_pass") is not None]
    ok_rows = [r for r in rows if r["run"]["ok"]]
    param_ok = [r["metrics"]["parameter_extraction_accuracy"] for r in ok_rows if r["metrics"].get("parameter_extraction_accuracy") is not None]
    fdg_node_ok = [r["metrics"]["fdg_node_f1"] for r in ok_rows if r["metrics"].get("fdg_node_f1") is not None]
    fdg_edge_ok = [r["metrics"]["fdg_edge_f1"] for r in ok_rows if r["metrics"].get("fdg_edge_f1") is not None]
    first_val_ok = [r["metrics"]["first_validation_pass"] for r in ok_rows if r["metrics"].get("first_validation_pass") is not None]
    return {
        "n": n,
        "ok": ok,
        "final_rate": ok / n if n else None,
        "pass1": pass1,
        "pass1_rate": pass1 / n if n else None,
        "param_extract_all": mean(param_all),
        "param_extract_ok": mean(param_ok),
        "fdg_node_all": mean(fdg_node_all),
        "fdg_node_ok": mean(fdg_node_ok),
        "fdg_edge_all": mean(fdg_edge_all),
        "fdg_edge_ok": mean(fdg_edge_ok),
        "first_validation_all": mean(first_val_all),
        "first_validation_ok": mean(first_val_ok),
        "metrics_ok_n": len(param_ok),
        "metrics_all_n": len(param_all),
        "avg_llm_repair": mean(
            [
                r["repair"]["validation_llm_attempts"] + r["repair"]["runtime_llm_attempts"]
                for r in ok_rows
            ]
        ),
        "failure_stage": dict(Counter((r["run"].get("error_stage") or "ok") for r in rows)),
    }


def summarize_merged_model(rows):
    n = len(rows)
    ok = sum(1 for r in rows if r["ok"])
    pass1 = sum(
        1
        for r in rows
        if r["ok"]
        and (r["repair"]["validation_llm_attempts"] + r["repair"]["runtime_llm_attempts"]) == 0
    )
    ok_rows = [r for r in rows if r["ok"]]
    param_ok = [r["metrics"]["parameter_extraction_accuracy"] for r in ok_rows if r["metrics"].get("parameter_extraction_accuracy") is not None]
    fdg_node_ok = [r["metrics"]["fdg_node_f1"] for r in ok_rows if r["metrics"].get("fdg_node_f1") is not None]
    fdg_edge_ok = [r["metrics"]["fdg_edge_f1"] for r in ok_rows if r["metrics"].get("fdg_edge_f1") is not None]
    first_val_ok = [r["metrics"]["first_validation_pass"] for r in ok_rows if r["metrics"].get("first_validation_pass") is not None]
    return {
        "n": n,
        "ok": ok,
        "final_rate": ok / n if n else None,
        "pass1": pass1,
        "pass1_rate": pass1 / n if n else None,
        "param_extract_ok": mean(param_ok),
        "fdg_node_ok": mean(fdg_node_ok),
        "fdg_edge_ok": mean(fdg_edge_ok),
        "first_validation_ok": mean(first_val_ok),
        "metrics_ok_n": len(param_ok),
        "avg_llm_repair": mean(
            [
                r["repair"]["validation_llm_attempts"] + r["repair"]["runtime_llm_attempts"]
                for r in ok_rows
            ]
        ),
    }


GLM_BASE = OUT
Q_BASE = OUT
DS_BASE = OUT


def task_batches(base, mapping):
    out = {}
    for tid in (f"T{i:02d}" for i in range(1, 41)):
        key = next((k for k in mapping if mapping[k][0] <= tid <= mapping[k][1]), None)
        out[tid] = base / mapping[key][2]
    return out


ds_roots = task_batches(
    DS_BASE,
    {
        "a": ("T01", "T10", "_ds_flash_T01_T10_100"),
        "b": ("T11", "T20", "_ds_flash_T11_T20_100"),
        "c": ("T21", "T30", "_ds_flash_T21_T30_100"),
        "d": ("T31", "T40", "_ds_flash_T31_T40_100"),
    },
)
glm_roots = task_batches(
    GLM_BASE,
    {
        "a": ("T01", "T04", "_glm_5_2_T01_T04_40"),
        "b": ("T05", "T14", "_glm_5_2_T05_T14_100"),
        "c": ("T15", "T24", "_glm_5_2_T15_T24_100"),
        "d": ("T25", "T30", "_glm_5_2_T25_T34_100"),
        "e": ("T31", "T40", "_glm_5_2_T31_T40_100"),
    },
)
qwen_roots = task_batches(
    Q_BASE,
    {
        "a": ("T01", "T04", "_qwen3_7_T01_T04_40"),
        "b": ("T05", "T14", "_qwen3_7_T05_T40_360"),
        "c": ("T15", "T24", "_qwen3_7_T15_T24_100"),
        "d": ("T25", "T40", "_qwen3_7_T25_T40_160"),
    },
)


def collect_task_scoped(roots_by_task):
    records = {}
    for tid, root in roots_by_task.items():
        run_root = root / "runs"
        if not run_root.exists():
            continue
        for method_dir in run_root.iterdir():
            if not method_dir.is_dir():
                continue
            for run_dir in method_dir.glob(f"{tid}/seed_*/latest"):
                seed = int(run_dir.parent.name.split("_")[1])
                run = load_run(run_dir)
                rep = load_repair_summary(run_dir)
                met = load_metrics(run_dir)
                if (tid, seed) in records:
                    old = records[(tid, seed)]
                    new_t = run.get("collected_at") or ""
                    old_t = old["run"].get("collected_at") or ""
                    if new_t <= old_t:
                        continue
                records[(tid, seed)] = {
                    "task": tid,
                    "seed": seed,
                    "run": run,
                    "repair": rep,
                    "metrics": met,
                }
    return records


ds_flash = collect_task_scoped(ds_roots)
glm52 = collect_task_scoped(glm_roots)
qwen37 = collect_task_scoped(qwen_roots)

model_summary = {
    "AeroDisk-LLM (v4-pro merged)": summarize_merged_model(merged),
    "AeroDisk-LLM (v4-pro raw 400)": summarize_model(
        {
            (tid, seed): {
                "task": tid,
                "seed": seed,
                "run": load_run(FULL_AGENTIC / tid / f"seed_{seed}" / "latest"),
                "repair": load_repair_summary(FULL_AGENTIC / tid / f"seed_{seed}" / "latest"),
                "metrics": load_metrics(FULL_AGENTIC / tid / f"seed_{seed}" / "latest"),
            }
            for tid in task_meta
            for seed in range(10)
        }
    ),
    "DeepSeek v4-flash": summarize_model(ds_flash),
    "GLM5.2": summarize_model(glm52),
    "Qwen3.7-Plus": summarize_model(qwen37),
}


# ---------------------------------------------------------------------------
# geometry quality from the merged 400 (318 success samples)
# ---------------------------------------------------------------------------
def geometry_quality():
    rows = []
    for r in merged:
        if not r["ok"]:
            continue
        met = r["metrics"]
        if met.get("key_dimension_relative_error") is None:
            continue
        rows.append(
            {
                "task": r["task"],
                "seed": r["seed"],
                "level": r["level"],
                "slot": r["slot"],
                "key_err": met["key_dimension_relative_error"],
                "vol_err": met.get("volume_relative_error"),
                "surf_err": met.get("surface_relative_error"),
                "step_ok": met.get("step_roundtrip_ok"),
                "hausdorff": met.get("slot_hausdorff_normalized"),
                "reg_ok": met.get("regeneration_ok"),
                "reg_skip": met.get("regeneration_skipped"),
            }
        )
    out = {"n": len(rows)}
    key = [r["key_err"] for r in rows if r["key_err"] is not None]
    vol = [r["vol_err"] for r in rows if r["vol_err"] is not None]
    surf = [r["surf_err"] for r in rows if r["surf_err"] is not None]
    step_ok = [r["step_ok"] for r in rows if r["step_ok"] is not None]
    haus = [r["hausdorff"] for r in rows if r["hausdorff"] is not None]
    reg_ok = [r for r in rows if r["reg_ok"] is not None]
    out["key_dim"] = {
        "mean": mean(key),
        "p95": sorted(key)[max(0, int(round(0.95 * len(key))) - 1)] if key else None,
        "max": max(key) if key else None,
        "n": len(key),
    }
    out["volume"] = {"mean": mean(vol), "n": len(vol)}
    out["surface"] = {"mean": mean(surf), "n": len(surf)}
    out["step_roundtrip"] = {"pass": sum(1 for v in step_ok if v is True), "n": len(step_ok)}
    out["hausdorff"] = {"mean": mean(haus), "n": len(haus)}
    out["regen"] = {
        "ok": sum(1 for r in reg_ok if r["reg_ok"]),
        "fail": sum(1 for r in reg_ok if not r["reg_ok"]),
        "n": len(reg_ok),
    }
    out["by_level"] = {}
    for lv in ["L1", "L2", "L3", "L4"]:
        sub = [r for r in rows if r["level"] == lv]
        k = [r["key_err"] for r in sub if r["key_err"] is not None]
        out["by_level"][lv] = {
            "n": len(sub),
            "avg_key_dim": mean(k),
            "avg_vol": mean([r["vol_err"] for r in sub if r["vol_err"] is not None]),
            "avg_surf": mean([r["surf_err"] for r in sub if r["surf_err"] is not None]),
        }
    out["by_slot"] = {
        "slot": {
            "n": sum(1 for r in rows if r["slot"]),
            "avg_key_dim": mean([r["key_err"] for r in rows if r["slot"]]),
            "hausdorff": mean([r["hausdorff"] for r in rows if r["slot"] and r["hausdorff"] is not None]),
            "hausdorff_n": sum(1 for r in rows if r["slot"] and r["hausdorff"] is not None),
        },
        "no_slot": {
            "n": sum(1 for r in rows if not r["slot"]),
            "avg_key_dim": mean([r["key_err"] for r in rows if not r["slot"]]),
        },
    }
    return out


geometry = geometry_quality()


# ---------------------------------------------------------------------------
# failure analysis
# ---------------------------------------------------------------------------
def failure_analysis():
    rows = merged
    failed = [r for r in rows if not r["ok"]]
    out = {"n": len(failed)}
    stage = Counter()
    detail = Counter()
    level = Counter()
    slot = Counter()
    for r in failed:
        replay_covered = (
            r["task"] == "T14"
            or "T15" <= r["task"] <= "T31"
            or (r["task"] == "T32" and r["seed"] <= 2)
        )
        if replay_covered:
            code = r["repair"].get("stop_code") or ""
            if code in ("", "success"):
                st = "mcp_gate"  # repair loop succeeded, engineering gate failed
            elif "runtime_attempts_exhausted" in code or code.startswith("runtime"):
                st = "runtime"
            elif "non_repairable" in code or "governor_stop" in code or code.startswith("validation"):
                st = "validation"
            else:
                st = code or "unknown"
        else:
            st = r["run"].get("error_stage")
            if st is None:
                st = r["metrics"].get("failure_category") or "unknown"
        stage[st] += 1
        code = r["run"].get("error_code") if not replay_covered else (r["repair"].get("stop_code") or "engineering_gate")
        if code:
            detail[(st, code)] += 1
        else:
            detail[(st, "no_code")] += 1
        level[r["level"]] += 1
        if r["slot"]:
            slot["slot"] += 1
        else:
            slot["no_slot"] += 1
    out["stage"] = dict(stage)
    out["detail"] = {f"{k[0]} :: {k[1]}": v for k, v in detail.most_common(40)}
    out["level"] = dict(level)
    out["slot"] = dict(slot)

    # raw full_agentic 400 batch: failure stage + mcp gate check categories
    raw_stage = Counter()
    gate = Counter()
    gate_runs = 0
    for tid in task_meta:
        for seed in range(10):
            d = FULL_AGENTIC / tid / f"seed_{seed}" / "latest"
            run = load_run(d)
            if not run["ok"]:
                raw_stage[run.get("error_stage") or "unknown"] += 1
            g = load_json(d / "mcp_gate.json", {})
            fc = g.get("failed_checks") or []
            if fc:
                gate_runs += 1
                for c in fc:
                    gate[c] += 1
    out["raw_full_agentic_stage"] = dict(raw_stage)
    out["mcp_gate_failed_checks"] = dict(gate)
    out["mcp_gate_failed_runs"] = gate_runs
    return out


failures = failure_analysis()


# ---------------------------------------------------------------------------
# repair diagnostics
# ---------------------------------------------------------------------------
def repair_diagnostics():
    rows = merged
    needed = [r for r in rows if (r["repair"]["validation_llm_attempts"] + r["repair"]["runtime_llm_attempts"]) > 0]
    val_needed = [r for r in rows if r["repair"]["validation_llm_attempts"] > 0]
    run_needed = [r for r in rows if r["repair"]["runtime_llm_attempts"] > 0]
    out = {
        "runs_entering_llm_repair": len(needed),
        "runs_entering_validation_repair": len(val_needed),
        "runs_entering_runtime_repair": len(run_needed),
        "repair_success_rate": mean([r["ok"] for r in needed]) if needed else None,
        "validation_repair_success_rate": mean([r["ok"] for r in val_needed]) if val_needed else None,
        "runtime_repair_success_rate": mean([r["ok"] for r in run_needed]) if run_needed else None,
        "round_distribution_success": dict(
            Counter(
                r["repair"]["validation_llm_attempts"] + r["repair"]["runtime_llm_attempts"]
                for r in needed
                if r["ok"]
            )
        ),
        "accepted_patch_total": sum(len(r["repair"]["accepted_patches"]) for r in needed),
        "rejected_patch_total": sum(len(r["repair"]["rejected_patches"]) for r in needed),
    }
    # diagnostics coverage: failed runs with structured stage/code
    failed = [r for r in rows if not r["ok"]]
    out["failed_diagnostics_coverage"] = sum(
        1 for r in failed if r["run"].get("error_stage") or r["repair"].get("stop_code")
    )
    out["failed_n"] = len(failed)
    return out


repair = repair_diagnostics()


# ---------------------------------------------------------------------------
# ablation (use existing summary + recompute repair-level stats)
# ---------------------------------------------------------------------------
def ablation_summary():
    abs_sum = load_json(OUT / "_ablation_deepseek_v4pro_seeds3" / "ablation_summary.json", {})
    rows = {}
    for row in abs_sum.get("rows", []):
        rows[row["method_id"]] = row
    return rows


ablation = ablation_summary()


# ---------------------------------------------------------------------------
# assemble and write
# ---------------------------------------------------------------------------
result = {
    "generated_at": "2026-08-31T05:30:00+08:00",
    "main_merged_400": main_summary,
    "model_comparison": model_summary,
    "geometry_quality": geometry,
    "failure_analysis": failures,
    "repair_diagnostics": repair,
    "ablation": ablation,
}

out_path = OUT / "paper_metrics_all.json"
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", out_path)

# human-readable block
lines = []
lines.append("## 主实验（合并 400）")
lines.append("| 分组 | N | 成功 | FinalSuccess@3 | Pass@1 | Pass@1率 | 平均LLM修复(全部) | 平均LLM修复(成功) | 平均总修复轮数(n) | 平均关键尺寸误差(%) |")
for g in ["overall", "L1", "L2", "L3", "L4", "slot", "no_slot"]:
    s = main_summary[g]
    avg_rounds = s["avg_total_repair_rounds"]
    avg_rounds_s = f"{avg_rounds:.3f}" if avg_rounds is not None else "N/A"
    key_err_s = f"{s['avg_key_dim_error']:.3f}" if s["avg_key_dim_error"] is not None else "N/A"
    lines.append(
        f"| {g} | {s['n']} | {s['ok']} | {fmt_pct(s['final_rate'])} | {s['pass1']} | "
        f"{fmt_pct(s['pass1_rate'])} | {s['avg_llm_repair_all']:.3f} | "
        f"{s['avg_llm_repair_success']:.3f} | "
        f"{avg_rounds_s} (n={s['repair_rounds_coverage']}) | "
        f"{key_err_s} (n={s['key_dim_error_n']}) |"
    )
lines.append("")
lines.append("## 模型对比")
for name, s in model_summary.items():
    lines.append(
        f"| {name} | N={s['n']} ok={s['ok']} final={fmt_pct(s['final_rate'])} "
        f"pass1={fmt_pct(s['pass1_rate'])} param_ok={fmt_pct(s.get('param_extract_ok'), 1)} "
        f"fdgN_ok={fmt_pct(s.get('fdg_node_ok'), 1)} fdgE_ok={fmt_pct(s.get('fdg_edge_ok'), 1)} "
        f"first_val_ok={fmt_pct(s.get('first_validation_ok'), 1)} "
        f"metrics_ok_n={s.get('metrics_ok_n')} |"
    )
lines.append("")
lines.append("## 几何质量")
g = geometry
lines.append(
    f"n={g['n']} key_mean={g['key_dim']['mean']:.3f}% p95={g['key_dim']['p95']:.3f}% "
    f"max={g['key_dim']['max']:.3f}% vol={g['volume']['mean']:.3f}% surf={g['surface']['mean']:.3f}% "
    f"step={g['step_roundtrip']['pass']}/{g['step_roundtrip']['n']} hausdorff={g['hausdorff']['mean']} n={g['hausdorff']['n']}"
)
lines.append("")
lines.append("## 失败")
lines.append(f"failed={failures['n']} stage={failures['stage']}")
lines.append("")
lines.append("## 修复诊断")
lines.append(json.dumps(repair, ensure_ascii=False))

print("\n".join(lines))
