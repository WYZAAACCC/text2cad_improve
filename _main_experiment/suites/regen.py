"""800-perturbation regeneration suite (single/double/3-5/cross-feature)."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from ..adapters import call_mcp_tool
from ..config import ExperimentConfig
from ..paths import experiment_output_root
from ..schemas import TaskSpec
from ..utils import atomic_write_json
from .base import copy_run_dir, ensure_golden, quality_ok, stamp_record, suite_root

_PARAM_POOL = {
    "slot": ["slot_count", "slot_distribution_radius", "slot_axial_depth",
             "root_fillet", "flank_fillet", "lobe_top_fillet"],
    "hole": ["hole_count"],
    "groove": ["groove_depth"],
    "disc": ["disc_hub_web_fillet", "disc_web_rim_fillet", "bore_diameter"],
}


def _applicable_groups(params: dict[str, Any]) -> list[str]:
    groups = ["disc"]
    if (params.get("slots") or 0) > 0:
        groups.append("slot")
    if (params.get("holes") or 0) > 0:
        groups.append("hole")
    if (params.get("grooves") or 0) > 0:
        groups.append("groove")
    return groups


def _category_for(i: int) -> str:
    return ["single", "double", "triple_five", "cross_feature"][i % 4]


def _available_params(task: TaskSpec, config: ExperimentConfig) -> set[str]:
    from .base import ensure_golden
    gold = ensure_golden(task, config)
    listed = call_mcp_tool("list_regeneratable_params", {"base_dir": str(gold)})
    return {p["param_key"] for p in listed.get("parameters", [])
            if p.get("current") is not None}


def _pick_params(groups: list[str], category: str, rng: random.Random,
                 available: set[str]) -> list[str]:
    pool_by_group = {g: [p for p in _PARAM_POOL[g] if p in available]
                     for g in groups}
    if category == "single":
        pool = [p for g in groups for p in pool_by_group[g]]
        return [rng.choice(pool)] if pool else []
    if category == "double":
        pool = [p for g in groups for p in pool_by_group[g]]
        return rng.sample(pool, min(2, len(pool))) if len(pool) >= 2 else (list(pool) if pool else [])
    if category == "triple_five":
        pool = [p for g in groups for p in pool_by_group[g]]
        return rng.sample(pool, min(5, len(pool))) if pool else []
    # cross_feature: at least two different feature groups
    chosen: list[str] = []
    usable_groups = [g for g in groups if pool_by_group[g]]
    gs = rng.sample(usable_groups, min(2, len(usable_groups)))
    for g in gs:
        chosen.append(rng.choice(pool_by_group[g]))
    return chosen


def build_tasks(config: ExperimentConfig, *, seed: int = 0) -> list[dict[str, Any]]:
    from ..aggregate import load_tasks
    tasks = load_tasks(config)
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    for tidx, task in enumerate(tasks):
        groups = _applicable_groups(task.normalized_params)
        available = _available_params(task, config)
        for pidx in range(20):  # 40 tasks × 20 = 800
            category = _category_for(pidx)
            keys = _pick_params(groups, category, rng, available=available)
            if not keys:
                continue
            updates = []
            for key in keys:
                delta = round(rng.uniform(-0.10, 0.10), 4)
                # 20% of samples deliberately target the feasible-boundary zone
                if rng.random() < 0.2:
                    delta = round(rng.choice([-0.98, 0.98]) * rng.uniform(0.5, 1.0), 4)
                updates.append({"param_key": key, "delta": delta})
            out.append({
                "task_id": task.task_id,
                "perturbation_id": f"{task.task_id}_P{pidx:03d}",
                "category": category,
                "param_updates": updates,
                "seed": seed,
            })
    return out


def _new_value(cur: float, delta: float, lo: float, hi: float) -> float:
    v = float(cur) * (1.0 + delta)
    return round(max(float(lo), min(float(hi), v)), 3)


def run_perturbation(
    task: TaskSpec,
    pert: dict[str, Any],
    config: ExperimentConfig,
) -> dict[str, Any]:
    gold = ensure_golden(task, config)
    run_dir = suite_root(config, "regen") / "runs" / pert["perturbation_id"]
    copy_run_dir(gold, run_dir)
    listed = call_mcp_tool("list_regeneratable_params", {"base_dir": str(run_dir)})
    current = {p["param_key"]: p["current"] for p in listed.get("parameters", [])}
    ranges = {p["param_key"]: p["range"] for p in listed.get("parameters", [])}
    param_types = {p["param_key"]: p.get("type") for p in listed.get("parameters", [])}
    updates = []
    margins = []
    for u in pert["param_updates"]:
        key = u["param_key"]
        if key not in current or current[key] is None or key not in ranges:
            continue
        lo, hi = ranges[key]
        new = _new_value(current[key], u["delta"], lo, hi)
        if param_types.get(key) == "int":
            new = max(float(lo), min(float(hi), round(new)))
            new = int(new)
        updates.append({"param_key": key, "new_value": new})
        width = max(1e-9, float(hi) - float(lo))
        margins.append(min(float(new) - float(lo), float(hi) - float(new)) / width)
    margin = min(margins) if margins else 1.0
    margin_group = "far" if margin > 0.30 else ("near" if margin < 0.05 else "mid")
    if not updates:
        return {"perturbation_id": pert["perturbation_id"], "ok": False,
                "reason": "no_applicable_params", "category": pert["category"]}
    res = call_mcp_tool("regenerate_model", {
        "base_dir": str(run_dir), "param_updates": updates})
    new_base = res.get("new_base_dir")
    base = Path(new_base) if res.get("ok") and new_base else run_dir
    gate = quality_ok(base)
    return {
        "perturbation_id": pert["perturbation_id"],
        "task_id": pert["task_id"],
        "category": pert["category"],
        "margin": round(margin, 4),
        "margin_group": margin_group,
        "regenerated_ok": bool(res.get("ok")),
        "quality_ok": bool(gate.get("ok")),
        "failed_checks": gate.get("failed_checks", []),
        "reason": res.get("reason") or res.get("detail") or "",
    }


def run_suite(
    tasks: list[TaskSpec],
    perturbations: list[dict[str, Any]],
    config: ExperimentConfig,
) -> list[dict[str, Any]]:
    task_map = {t.task_id: t for t in tasks}
    results = []
    for pert in perturbations:
        task = task_map.get(pert["task_id"])
        if task is None:
            continue
        try:
            res = run_perturbation(task, pert, config)
            results.append(stamp_record(res, "regen", "regen_v1"))
        except Exception as exc:  # noqa: BLE001
            res = {"perturbation_id": pert["perturbation_id"], "ok": False,
                   "reason": str(exc)[:300], "category": pert["category"]}
            results.append(stamp_record(res, "regen", "regen_v1"))
    return results


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    def _rate(items: list[dict[str, Any]]) -> float:
        return round(sum(1 for r in items if r.get("regenerated_ok") and r.get("quality_ok"))
                     / max(1, len(items)), 4)
    rows = []
    for cat in ("single", "double", "triple_five", "cross_feature"):
        items = [r for r in results if r.get("category") == cat]
        rows.append({"category": cat, "runs": len(items), "regen_success": _rate(items)})
    for group in ("far", "mid", "near"):
        items = [r for r in results if r.get("margin_group") == group]
        rows.append({"margin_group": group, "runs": len(items),
                     "regen_success": _rate(items)})
    rows.append({"overall": True, "runs": len(results), "regen_success": _rate(results)})
    return {"rows": rows}
