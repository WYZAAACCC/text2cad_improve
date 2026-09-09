"""Aggregate GLM / DeepSeek-v4flash / Qwen3.7 run batches into one row each.

Historical model rows follow their original engineering-gate口径:
FinalSuccess@3 = run.ok (three repair rounds through validation, CAD execution
and the engineering gate); Engineering Pass@1 = run.ok with zero LLM repair
attempts. The 1% volume/surface geometry gate is NOT applied to these runs.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"

TASKS = {t["task_id"]: t for t in
         json.loads((OUT / "tasks.json").read_text(encoding="utf-8"))}

MODELS = [
    ("glm_5_2", [
        "_glm_5_2_T01_T04_40", "_glm_5_2_T05_T14_100",
        "_glm_5_2_T15_T24_100", "_glm_5_2_T25_T34_100",
        "_glm_5_2_T31_T40_100",
    ], "full_agentic_glm_5_2"),
    ("ds_v4flash", [
        "_ds_flash_T01_T10_100", "_ds_flash_T11_T20_100",
        "_ds_flash_T21_T30_100", "_ds_flash_T31_T40_100",
    ], "full_agentic_ds_flash"),
    ("qwen3_7_plus", [
        "_qwen3_7_T01_T04_40", "_qwen3_7_T01_T10_100",
        "_qwen3_7_T05_T40_360",
        "_qwen3_7_T15_T24_100", "_qwen3_7_T25_T40_160",
        "_qwen3_7_smoke10e", "_qwen3_7_smoke10",
    ], "full_agentic_qwen3_7_plus"),
]


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _iso_secs(s, f):
    if not s or not f:
        return None
    try:
        return (datetime.fromisoformat(f.replace("Z", "+00:00"))
                - datetime.fromisoformat(s.replace("Z", "+00:00"))).total_seconds()
    except Exception:
        return None


def _aggregate(batches: list[str], method_id: str) -> list[dict]:
    rows_by_key = {}
    for batch in batches:
        method_root = OUT / batch / "runs" / method_id
        if not method_root.exists():
            continue
        for task_dir in method_root.iterdir():
            if not task_dir.is_dir():
                continue
            task = task_dir.name
            for seed_dir in task_dir.iterdir():
                if not seed_dir.is_dir() or not seed_dir.name.startswith("seed_"):
                    continue
                seed = int(seed_dir.name.split("_")[1])
                latest = seed_dir / "latest"
                run_json = latest / "run.json"
                if not run_json.exists():
                    continue
                run = _read(run_json)
                if not run:
                    continue
                mtime = run_json.stat().st_mtime
                key = (task, seed)
                if key in rows_by_key and rows_by_key[key]["_mtime"] >= mtime:
                    continue
                metrics = _read(latest / "metrics.json") or []
                vals = {x.get("metric_id"): x.get("value") for x in metrics}
                repair = _read(latest / "repair_summary.json") or {}
                outcome = repair.get("outcome") or {}
                llm = int(outcome.get("validation_llm_attempts") or 0) \
                    + int(outcome.get("runtime_llm_attempts") or 0)
                usage = run.get("usage") or {}
                rows_by_key[key] = {
                    "task": task, "seed": seed,
                    "level": TASKS.get(task, {}).get("level"),
                    "ok": bool(run.get("ok")),
                    "error_stage": run.get("error_stage"),
                    "vol": vals.get("volume_relative_error"),
                    "surf": vals.get("surface_relative_error"),
                    "key": vals.get("key_dimension_relative_error"),
                    "step": vals.get("step_roundtrip_ok"),
                    "slot_haus_mm": vals.get("slot_haus_normalized"),
                    "llm_repair": llm,
                    "tokens": usage.get("total_tokens"),
                    "seconds": _iso_secs(run.get("started_at"), run.get("finished_at")),
                    "_mtime": mtime,
                }
    return [dict(v) for v in rows_by_key.values()]


def _summarize(rows: list[dict]) -> dict:
    # Raw engineering success is the only formal metric for historical models.
    eng = [r for r in rows if r["ok"]]
    pass1 = [r for r in eng if r.get("llm_repair") == 0]

    vol = [r["vol"] for r in eng]
    surf = [r["surf"] for r in eng]
    by_level = {}
    for lv in ("L1", "L2", "L3", "L4"):
        e = [r for r in eng if r["level"] == lv]
        p = [r for r in pass1 if r["level"] == lv]
        by_level[lv] = {
            "total": sum(1 for r in rows if r["level"] == lv),
            "final_success": len(e),
            "engineering_pass1": len(p),
        }
    return {
        "n": len(rows),
        "mcp_ok": len(eng),
        "final_success": len(eng),
        "final_success_rate": len(eng) / len(rows) if rows else None,
        "engineering_pass1": len(pass1),
        "engineering_pass1_rate": len(pass1) / len(rows) if rows else None,
        "by_level": by_level,
        "vol_mean_pct": statistics.fmean([v for v in vol if v is not None]) if any(v is not None for v in vol) else None,
        "surf_mean_pct": statistics.fmean([v for v in surf if v is not None]) if any(v is not None for v in surf) else None,
        "key_mean_pct": statistics.fmean([r["key"] for r in eng if r.get("key") is not None]) if any(r.get("key") is not None for r in eng) else None,
        "avg_tokens": statistics.fmean([r["tokens"] for r in rows if r.get("tokens") is not None]) if any(r.get("tokens") is not None for r in rows) else None,
        "avg_seconds": statistics.fmean([r["seconds"] for r in rows if r.get("seconds") is not None]) if any(r.get("seconds") is not None for r in rows) else None,
        "records": rows,
    }


def main() -> None:
    results = {}
    for name, batches, method in MODELS:
        results[name] = _summarize(_aggregate(batches, method))
    dest = OUT / "MODEL_COMPARISON_PLACEHOLDER.json"
    dest.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "records"}
                      for k, v in results.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
