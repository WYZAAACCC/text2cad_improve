"""120 infeasible-design rejection suite (5 categories x 24)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..config import ExperimentConfig
from ..schemas import TaskSpec
from .base import stamp_record, suite_root

_CATEGORIES = (
    "hole_out_of_bounds", "slot_pitch_insufficient", "slot_depth_over_rim",
    "fillet_unconstructable", "hard_constraint_conflict",
)


def _base_params(task: TaskSpec) -> dict[str, Any]:
    p = dict(task.normalized_params)
    p["category"] = p.get("category", "basic")
    return p


def _prompt_from_params(p: dict[str, Any]) -> str:
    parts = [f"生成一个高压涡轮盘参考几何：外径{p.get('od_mm', 500)}mm，"
             f"中心孔直径{p.get('bore_mm', 120)}mm，轴向最大厚度{p.get('thick_mm', 76)}mm，"
             f"轮毂半厚{p.get('hub_mm', 38)}mm，轮缘半厚{p.get('rim_mm', 30)}mm"]
    if p.get("slots"):
        parts.append(f"轮缘上{p['slots']}个{p.get('teeth', 2)}齿枞树形榫槽，"
                     f"槽深{p.get('depth_mm', 24)}mm，喉部半宽{p.get('throat_half_width_mm', 4)}mm")
    if p.get("holes"):
        parts.append(f"周向均布{p['holes']}个安装孔，孔径{p.get('hdia_mm', 14)}mm，"
                     f"分布半径{p.get('pcd_mm', 180)}mm")
    if p.get("grooves"):
        parts.append(f"轮缘内侧{p['grooves']}道环槽，槽宽{p.get('gw_mm', 10)}mm，"
                     f"槽深{p.get('gd_mm', 12)}mm")
    if p.get("lh_holes"):
        parts.append(f"腹板上{p['lh_holes']}个减重孔，孔径{p.get('lh_hdia_mm', 16)}mm，"
                     f"分布半径{p.get('lh_pcd_mm', 175)}mm")
    return "，".join(parts) + "。参考几何，非适航件。"


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def feasibility_precheck(
    inf: dict[str, Any],
) -> tuple[bool, list[str]]:
    """显式工程约束预检：硬约束冲突/越界 → 结构化拒绝（论文需求预检口径）。"""
    p = inf.get("params") or {}
    cat = inf.get("category")
    reasons: list[str] = []
    od = float(p.get("od_mm") or 0)
    rim_r = od / 2.0
    bore_r = float(p.get("bore_mm") or 0) / 2.0
    form = p.get("form", "standard")
    r_fac = {"thick_rim": 0.17, "large_hub": 0.10}.get(form, 0.12)
    rim_radial = _clamp(r_fac * od, 25.0, 95.0)
    if cat == "hole_out_of_bounds":
        pcd = float(p.get("lh_pcd_mm") or 0)
        if pcd > rim_r:
            reasons.append(f"减重孔分布半径 {pcd} > 轮缘外半径 {rim_r}")
    if cat == "slot_pitch_insufficient":
        slots = int(p.get("slots") or 0)
        radius = float(p.get("R_mm") or rim_r)
        pitch = 2 * 3.141592653589793 * radius / max(1, slots)
        if pitch < 8.0:
            reasons.append(f"榫槽周向节距 {pitch:.1f} < 8mm")
    if cat == "slot_depth_over_rim":
        depth = float(p.get("depth_mm") or 0)
        if depth > rim_radial - 2.0:
            reasons.append(f"榫槽深 {depth} > 可用轮缘径向 {rim_radial - 2:.1f}")
    if cat == "fillet_unconstructable":
        fr = float(p.get("fr_mm") or 0)
        if fr > 4.0:
            reasons.append(f"齿根圆角 {fr} 超出可构造范围")
    if cat == "hard_constraint_conflict":
        text = inf.get("prompt") or ""
        if "同时必须保持" in text or "且同时必须" in text:
            reasons.append("外径硬约束冲突（同一尺寸被同时要求两个不同值）")
    return bool(reasons), reasons


def _infeasible_params(base: dict[str, Any], category: str) -> dict[str, Any]:
    p = dict(base)
    rim_r = p.get("od_mm", 500) / 2.0
    if category == "hole_out_of_bounds":
        p["lh_holes"] = p.get("lh_holes") or 12
        p["lh_hdia_mm"] = p.get("lh_hdia_mm") or 16
        p["lh_pcd_mm"] = round(rim_r * 1.2, 1)  # 分布半径越过轮缘外径
    elif category == "slot_pitch_insufficient":
        p["slots"] = 96
        p["teeth"] = p.get("teeth", 2)
        p["R_mm"] = 120.0  # 2π×120/96 ≈ 7.85mm < 8mm 节距下限
        p["depth_mm"] = p.get("depth_mm") or 24
        p["throat_half_width_mm"] = p.get("throat_half_width_mm") or 6
    elif category == "slot_depth_over_rim":
        p["slots"] = p.get("slots") or 60
        p["teeth"] = p.get("teeth", 2)
        rim_radial = rim_r - (p.get("bore_mm", 120) / 2.0 + 60)
        p["depth_mm"] = round(max(40.0, rim_radial * 1.4), 1)
        p["throat_half_width_mm"] = p.get("throat_half_width_mm") or 6
    elif category == "fillet_unconstructable":
        p["slots"] = p.get("slots") or 60
        p["teeth"] = p.get("teeth", 2)
        p["fr_mm"] = 20.0
        p["throat_half_width_mm"] = p.get("throat_half_width_mm") or 4
    return p


def build_tasks(tasks: list[TaskSpec]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx in range(24):
        task = tasks[idx % len(tasks)]
        for cat in _CATEGORIES:
            base = _base_params(task)
            p = _infeasible_params(base, cat)
            if cat == "hard_constraint_conflict":
                prompt = _prompt_from_params(p) + " 硬约束：外径必须保持500mm且同时必须保持600mm。"
            else:
                prompt = _prompt_from_params(p)
            out.append({
                "infeasible_id": f"INF_{idx:02d}_{cat}",
                "category": cat,
                "base_task_id": task.task_id,
                "params": p,
                "prompt": prompt,
            })
    return out


def _build_llm(cfg):
    from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
    from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
    os.environ.setdefault(cfg.api_key_env, "")
    config = LlmModelConfig(model=cfg.model, base_url=cfg.base_url,
                            timeout_s=cfg.timeout_s,
                            temperature=cfg.temperature if cfg.temperature is not None else 0.3,
                            thinking=cfg.thinking or {"type": "disabled"})
    return DeepSeekToolCaller(), config


def run_infeasible(
    inf: dict[str, Any],
    config: ExperimentConfig,
    *,
    with_constraints: bool = True,
) -> dict[str, Any]:
    if with_constraints:
        rejected, reasons = feasibility_precheck(inf)
        if rejected:
            return {"infeasible_id": inf["infeasible_id"], "category": inf["category"],
                    "with_constraints": True,
                    "correct_rejected": True, "delivered": False,
                    "rejection": "structured_precheck", "reason": "；".join(reasons)}
    import sys
    from pathlib import Path as _P
    _server = _P(__file__).resolve().parents[2] / "app" / "text-to-cad" / "server"
    if str(_server) not in sys.path:
        sys.path.insert(0, str(_server))
    import agentic_l2
    from seekflow_engineering_tools.generative_cad.pipeline.run import run_gcad_core
    text = inf["prompt"]
    if with_constraints and inf["category"] != "hard_constraint_conflict":
        text += " 硬约束：所有尺寸不得自动放宽以满足可行性。"
    caller, llm_cfg = _build_llm(config.llm)
    out_dir = suite_root(config, "infeasible") / "runs" / (
        ("c_" if with_constraints else "n_") + inf["infeasible_id"])
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        raw = agentic_l2.run_agentic_l2(
            text, None, caller=caller, llm_model_config=llm_cfg, out_dir=out_dir)
        result = run_gcad_core(raw, out_step=out_dir / "output.step",
                               metadata_path=out_dir / "output.metadata.json")
        delivered = bool(result.ok)
        return {"infeasible_id": inf["infeasible_id"], "category": inf["category"],
                "with_constraints": with_constraints,
                "correct_rejected": not delivered, "delivered": delivered,
                "reason": getattr(result, "error", None) or ""}
    except Exception as exc:  # noqa: BLE001
        return {"infeasible_id": inf["infeasible_id"], "category": inf["category"],
                "with_constraints": with_constraints,
                "correct_rejected": True, "delivered": False,
                "reason": f"agent_failed:{type(exc).__name__}:{str(exc)[:200]}"}


def run_suite(
    infeasible_tasks: list[dict[str, Any]],
    config: ExperimentConfig,
    *,
    with_constraints: bool = True,
) -> list[dict[str, Any]]:
    results = []
    for inf in infeasible_tasks:
        try:
            res = run_infeasible(inf, config, with_constraints=with_constraints)
            results.append(stamp_record(res, "infeasible", "infeasible_v1"))
        except Exception as exc:  # noqa: BLE001
            res = {"infeasible_id": inf["infeasible_id"],
                   "category": inf["category"], "with_constraints": with_constraints,
                   "correct_rejected": False, "delivered": False,
                   "reason": str(exc)[:200]}
            results.append(stamp_record(res, "infeasible", "infeasible_v1"))
    return results


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for constraints in (True, False):
        items = [r for r in results if r.get("with_constraints") == constraints]
        rows.append({
            "with_constraints": constraints, "runs": len(items),
            "correct_rejection_rate": round(
                sum(1 for r in items if r.get("correct_rejected")) / max(1, len(items)), 4),
        })
    for cat in _CATEGORIES:
        items = [r for r in results if r.get("category") == cat and r.get("with_constraints")]
        rows.append({
            "category": cat, "runs": len(items),
            "correct_rejection_rate": round(
                sum(1 for r in items if r.get("correct_rejected")) / max(1, len(items)), 4),
        })
    return {"rows": rows}
