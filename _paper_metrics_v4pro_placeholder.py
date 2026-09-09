"""Compute paper-required metrics from the new-code DeepSeek v4-pro 400 runs.

The four batches cover tasks T01-T40 x seeds 0-9. Success gate here:
MCP ok + volume_relative_error<=1% + surface_relative_error<=1%.
Pass@1 = gate-ok and zero LLM repair attempts (repair_summary).
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"

BATCHES = {
    0: "rerun_120_t1t40_3seeds", 1: "rerun_120_t1t40_3seeds",
    2: "rerun_120_t1t40_3seeds", 3: "rerun_120_t1t40_3seeds_b2",
    4: "rerun_120_t1t40_3seeds_b2", 5: "rerun_120_t1t40_3seeds_b2",
    6: "rerun_120_t1t40_3seeds_b3", 7: "rerun_120_t1t40_3seeds_b3",
    8: "rerun_120_t1t40_3seeds_b3", 9: "rerun_40_t1t40_seed9",
}

TASKS = {t["task_id"]: t for t in
         json.loads((OUT / "tasks.json").read_text(encoding="utf-8"))}


def _run_dir(task: str, seed: int) -> Path:
    batch = BATCHES[seed]
    return OUT / batch / "runs" / "smoke_generation_fix" / task / f"seed_{seed}" / "latest"


def _repair_llm_attempts(task: str, seed: int) -> int | None:
    p = _run_dir(task, seed) / "repair_summary.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        o = d.get("outcome") or {}
        return int(o.get("validation_llm_attempts") or 0) + int(o.get("runtime_llm_attempts") or 0)
    except Exception:
        return None


def _usage_seconds(task: str, seed: int) -> tuple[int | None, float | None]:
    p = _run_dir(task, seed) / "run.json"
    if not p.exists():
        return None, None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        usage = d.get("usage") or {}
        tokens = usage.get("total_tokens")
        s = d.get("started_at")
        f = d.get("finished_at")
        secs = None
        if s and f:
            fmt = "%Y-%m-%dT%H:%M:%S.%f+00:00"
            try:
                secs = (datetime.fromisoformat(f) - datetime.fromisoformat(s)).total_seconds()
            except Exception:
                try:
                    secs = (datetime.fromisoformat(f.replace("Z", "+00:00"))
                            - datetime.fromisoformat(s.replace("Z", "+00:00"))).total_seconds()
                except Exception:
                    secs = None
        return tokens, secs
    except Exception:
        return None, None


def _metric_value(task: str, seed: int, metric_id: str):
    p = _run_dir(task, seed) / "metrics.json"
    if not p.exists():
        return None
    try:
        for x in json.loads(p.read_text(encoding="utf-8")):
            if x.get("metric_id") == metric_id:
                return x.get("value")
    except Exception:
        return None
    return None


def main() -> None:
    rows = json.loads((OUT / "main_400_seed0to9" / "summary.json").read_text(encoding="utf-8"))["records"]
    for r in rows:
        t, s = r["task"], int(r["seed"])
        r["llm_repair"] = _repair_llm_attempts(t, s)
        r["tokens"], r["seconds"] = _usage_seconds(t, s)
        if r.get("vol") is not None and r["vol"] <= 1.0 and r["surf"] is not None and r["surf"] <= 1.0:
            r["gate_ok"] = True
        else:
            r["gate_ok"] = False
        r["level"] = TASKS[t]["level"]
        slot_ref = (TASKS[t].get("gold") or {}).get("slot_reference")
        r["teeth"] = slot_ref.get("teeth_count") if slot_ref else None
        r["param_extract"] = _metric_value(t, s, "parameter_extraction_accuracy")
        r["fdg_node_f1"] = _metric_value(t, s, "fdg_node_f1")
        r["fdg_edge_f1"] = _metric_value(t, s, "fdg_edge_f1")
        r["first_validation_pass"] = _metric_value(t, s, "first_validation_pass")

    gate = [r for r in rows if r["gate_ok"]]
    pass1 = [r for r in gate if r.get("llm_repair") == 0]
    fail = [r for r in rows if not r["gate_ok"]]

    def by_level(sub):
        out = {}
        for lv in ("L1", "L2", "L3", "L4"):
            s = [r for r in sub if r["level"] == lv]
            out[lv] = {"n": len(s), "ok": len(s)}
        return out

    vol = [r["vol"] for r in gate if r.get("vol") is not None]
    surf = [r["surf"] for r in gate if r.get("surf") is not None]
    key = [r["key"] for r in gate if r.get("key") is not None]
    param = [r["param_extract"] for r in gate if r.get("param_extract") is not None]
    fdg_node = [r["fdg_node_f1"] for r in gate if r.get("fdg_node_f1") is not None]
    fdg_edge = [r["fdg_edge_f1"] for r in gate if r.get("fdg_edge_f1") is not None]
    first_val = [r["first_validation_pass"] for r in gate if r.get("first_validation_pass") is not None]

    def p95(vals):
        vals = sorted(vals)
        if not vals:
            return None
        k = max(0, min(len(vals) - 1, int(round(0.95 * (len(vals) - 1)))))
        return vals[k]

    summary = {
        "model_placeholder": "AeroDisk-LLM (temporary: deepseek-v4-pro new-code 400)",
        "total": len(rows),
        "mcp_ok": sum(1 for r in rows if r["ok"]),
        "gate_ok": len(gate),
        "gate_rate": len(gate) / len(rows),
        "pass1_gate": len(pass1),
        "pass1_gate_rate": len(pass1) / len(rows),
        "by_level_gate": by_level(gate),
        "by_level_pass1": by_level(pass1),
        "vol_mean_pct": statistics.fmean(vol) if vol else None,
        "vol_p95_pct": p95(vol),
        "vol_max_pct": max(vol) if vol else None,
        "surf_mean_pct": statistics.fmean(surf) if surf else None,
        "surf_p95_pct": p95(surf),
        "surf_max_pct": max(surf) if surf else None,
        "key_mean_pct": statistics.fmean(key) if key else None,
        "key_p95_pct": p95(key),
        "key_max_pct": max(key) if key else None,
        "param_extract_mean_pct": statistics.fmean(param) * 100 if param else None,
        "param_extract_n": len(param),
        "fdg_node_mean_pct": statistics.fmean(fdg_node) * 100 if fdg_node else None,
        "fdg_edge_mean_pct": statistics.fmean(fdg_edge) * 100 if fdg_edge else None,
        "first_validation_mean_pct": statistics.fmean(first_val) * 100 if first_val else None,
        "step_pass": sum(1 for r in gate if r.get("step") is True),
        "slot_haus_mean_mm": statistics.fmean([r["slot_haus_mm"] for r in gate if r.get("slot_haus_mm") is not None]) if any(r.get("slot_haus_mm") is not None for r in gate) else None,
        "slot_haus_by_teeth": {
            str(t): statistics.fmean([r["slot_haus_mm"] for r in gate if r.get("teeth") == t and r.get("slot_haus_mm") is not None])
            for t in (2, 3, 4) if any(r.get("teeth") == t and r.get("slot_haus_mm") is not None for r in gate)
        },
        "slot_haus_n": sum(1 for r in gate if r.get("slot_haus_mm") is not None),
        "avg_tokens": statistics.fmean([r["tokens"] for r in rows if r.get("tokens") is not None]) if any(r.get("tokens") is not None for r in rows) else None,
        "avg_seconds": statistics.fmean([r["seconds"] for r in rows if r.get("seconds") is not None]) if any(r.get("seconds") is not None for r in rows) else None,
        "failures": [
            {"task": r["task"], "seed": r["seed"], "level": r["level"],
             "ok": r["ok"], "vol": r.get("vol"), "surf": r.get("surf"),
             "error_stage": r.get("error_stage")}
            for r in fail
        ],
    }
    dest = OUT / "AERODISK_PLACEHOLDER_SUMMARY.json"
    dest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
