"""Geometry and STEP metrics for successful benchmark runs."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..adapters import call_mcp_tool
from ..config import ExperimentConfig
from ..schemas import MetricResult, RunResult, TaskSpec


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _points_from_ir(ir: dict[str, Any]) -> list[tuple[float, float]]:
    for node in ir.get("nodes", []):
        if node.get("op") == "add_polyline":
            points = (node.get("params") or {}).get("points") or []
            if points:
                return [(float(p["x_mm"]), float(p["y_mm"])) for p in points]
    return []


def _slot_points_from_ir(ir: dict[str, Any]) -> list[tuple[float, float]]:
    """榫槽 cutter 的 add_polyline 轮廓点（按组件/节点命名定位，不用盘体第一个 polyline）。"""
    comp_kinds = {c.get("id"): c.get("kind_hint") for c in ir.get("components", [])}
    for node in ir.get("nodes", []):
        if node.get("op") != "add_polyline":
            continue
        nid = str(node.get("id", ""))
        cid = str(node.get("component", ""))
        kh = str(comp_kinds.get(node.get("component")) or "")
        if ("cutter" in nid or "slot" in nid or "cutter" in cid
                or "slot" in cid or "fir_tree" in kh or "slot" in kh):
            points = (node.get("params") or {}).get("points") or []
            if points:
                return [(float(p["x_mm"]), float(p["y_mm"])) for p in points]
    return []


def hausdorff_distance(
    a: list[tuple[float, float]],
    b: list[tuple[float, float]],
) -> float:
    if not a or not b:
        return float("inf")

    def one_sided(x, y):
        best = 0.0
        for px in x:
            best = max(best, min(math.dist(px, py) for py in y))
        return best

    return max(one_sided(a, b), one_sided(b, a))


def _key_dimension_error(
    expected: list[Any],
    measured: dict[str, Any],
) -> MetricResult | None:
    errors = []
    for dim in expected:
        actual = measured.get(dim.name)
        if actual is None:
            continue
        errors.append(abs(float(actual) - dim.expected_mm))
    if not errors:
        return None
    relative = sum(abs(float(measured[d.name]) - d.expected_mm) / d.expected_mm * 100.0
                   for d in expected if measured.get(d.name) is not None) / len(errors)
    return MetricResult(
        metric_id="key_dimension_relative_error",
        name="平均关键尺寸相对误差",
        value=round(relative, 6),
        unit="%",
        level="task",
        passed=max(errors) <= 0.05,
        notes=f"mean_abs_mm={round(sum(errors) / len(errors), 6)}",
    )


def _solid_stats(step_path: Path) -> dict[str, float] | None:
    try:
        import cadquery as cq
        obj = cq.importers.importStep(str(step_path))
        solids = obj.solids().vals()
        return {
            "solid_count": len(solids),
            "volume_mm3": round(sum(s.Volume() for s in solids), 6),
            "surface_mm2": round(sum(s.Area() for s in solids), 6),
        }
    except Exception:  # noqa: BLE001
        return None


def _relative_error_metric(metric_id, name, run_value, gold_value,
                           *, unit="ratio") -> MetricResult | None:
    if run_value is None or not gold_value:
        return None
    rel = abs(run_value - gold_value) / abs(gold_value) * 100.0
    return MetricResult(
        metric_id=metric_id, name=name, value=round(rel, 6), unit="%",
        level="task", passed=rel <= 1.0,
        notes=f"run={run_value} gold={gold_value}",
    )


class GeometryMetricsComputer:
    def compute(
        self,
        *,
        run_dir: Path,
        task_spec: TaskSpec,
        run_result: RunResult,
        config: ExperimentConfig,
    ) -> list[MetricResult]:
        metrics: list[MetricResult] = []
        if not run_result.ok:
            return [MetricResult(
                metric_id="geometry_skipped",
                name="几何指标",
                value=False,
                passed=False,
                notes="运行未成功，跳过几何计算",
            )]

        measured: dict[str, Any] = {}
        try:
            report = call_mcp_tool("generate_quality_report", {
                "base_dir": str(run_dir),
                "tool_subset": [
                    "measure_disc_dimensions",
                    "measure_fir_tree_slot_profile",
                    "check_solid_validity",
                    "validate_slot_step_roundtrip",
                ],
            })
            details = report.get("details") or {}
            for name in report.get("measurements", []):
                item = details.get(name)
                if isinstance(item, dict):
                    measured.update(item)
        except Exception:
            report = {}

        dim_error = _key_dimension_error(task_spec.gold.key_dimensions, measured)
        if dim_error is not None:
            metrics.append(dim_error)

        slot_ref = task_spec.gold.slot_reference
        if slot_ref is not None:
            try:
                run_ir = _load_json(run_dir / "raw_fixed.json")
                ref_ir = _load_json(task_spec.gold.canonical_ir_path)
                run_pts = _slot_points_from_ir(run_ir)
                ref_pts = _slot_points_from_ir(ref_ir)
                if run_pts and ref_pts:
                    distance = hausdorff_distance(run_pts, ref_pts)
                    normalized = distance / max(slot_ref.slot_depth_mm, 1e-9)
                    metrics.append(MetricResult(
                        metric_id="slot_hausdorff_normalized",
                        name="榫槽归一化Hausdorff距离",
                        value=round(normalized, 6),
                        unit="ratio",
                        level="task",
                        passed=normalized <= 0.05,
                    ))
            except Exception:
                pass

        roundtrip = report.get("ok", False) if isinstance(report, dict) else False
        metrics.append(MetricResult(
            metric_id="step_roundtrip_ok",
            name="STEP回读通过",
            value=roundtrip,
            passed=roundtrip,
        ))
        run_step = run_dir / "output.step"
        gold_step = task_spec.gold.step_path
        run_stats = _solid_stats(run_step) if run_step.exists() else None
        gold_stats = _solid_stats(gold_step) if gold_step.exists() else None
        if run_stats and gold_stats:
            for mid, name, key in (
                ("volume_relative_error", "体积相对误差", "volume_mm3"),
                ("surface_relative_error", "表面积相对误差", "surface_mm2"),
            ):
                metric = _relative_error_metric(
                    mid, name, run_stats.get(key), gold_stats.get(key))
                if metric is not None:
                    metrics.append(metric)
            if run_stats.get("solid_count") != gold_stats.get("solid_count"):
                metrics.append(MetricResult(
                    metric_id="solid_count_match", name="实体数量一致",
                    value=False, unit="ratio", level="task", passed=False,
                    notes=f"run={run_stats.get('solid_count')} gold={gold_stats.get('solid_count')}"))
        return metrics
