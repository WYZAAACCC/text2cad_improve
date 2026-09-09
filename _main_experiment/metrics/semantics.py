"""Semantic and IR metrics: parameters, FDG nodes/edges, first validation."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..config import ExperimentConfig
from ..schemas import MetricResult, RunResult, TaskSpec
from ..adapters import call_mcp_tool


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ir_nodes(ir: dict[str, Any]) -> list[dict[str, Any]]:
    return ir.get("nodes", [])


def _params_from_ir(ir: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for node in _ir_nodes(ir):
        for key, value in (node.get("params") or {}).items():
            if isinstance(value, (int, float, str, bool)):
                out[key] = value
    return out


def _close(a: Any, b: Any, tolerance: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), abs_tol=tolerance)
    return str(a) == str(b)


def parameter_accuracy(
    expected: dict[str, Any],
    actual: dict[str, Any],
    tolerance: float = 0.05,
) -> MetricResult:
    expected_items = [(k, v) for k, v in expected.items() if k in actual]
    matched = sum(1 for k, v in expected_items if _close(v, actual[k], tolerance))
    total = max(1, len(expected))
    return MetricResult(
        metric_id="parameter_accuracy",
        name="参数识别准确率",
        value=round(matched / total, 4),
        unit="ratio",
        level="task",
        passed=matched == len(expected),
    )


def _node_key(node: dict[str, Any]) -> tuple[str, str, str, str]:
    _NORM_COMPONENT = {
        "disc_body": "disc", "turbine_disc": "disc",
        "slot_cutter": "slot", "fir_tree_cutter": "slot",
    }
    comp = _NORM_COMPONENT.get(str(node.get("component", "")),
                               str(node.get("component", "")))
    return (
        comp,
        str(node.get("dialect", "")),
        str(node.get("op", "")),
        str(node.get("phase", "")),
    )


def _edge_keys(nodes: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    key_of = {str(n.get("id", "")): _node_key(n) for n in nodes}
    edges = set()
    for node in nodes:
        node_key = key_of.get(str(node.get("id", "")))
        for inp in node.get("inputs", []):
            src_id = str(inp.get("node") or inp.get("producer_node") or "")
            src_key = key_of.get(src_id)
            edges.add((src_key, str(inp.get("output", "")), node_key))
    return edges


def fdg_f1(
    reference_nodes: list[dict[str, Any]],
    actual_nodes: list[dict[str, Any]],
    *,
    kind: str,
) -> MetricResult:
    ref = {_node_key(n) for n in reference_nodes}
    act = {_node_key(n) for n in actual_nodes}
    if kind == "node":
        tp = len(ref & act)
        precision = tp / len(act) if act else 0.0
        recall = tp / len(ref) if ref else 0.0
        metric_id = "fdg_node_f1"
        name = "FDG操作节点F1"
    else:
        ref_edges = _edge_keys(reference_nodes)
        act_edges = _edge_keys(actual_nodes)
        tp = len(ref_edges & act_edges)
        precision = tp / len(act_edges) if act_edges else 0.0
        recall = tp / len(ref_edges) if ref_edges else 0.0
        metric_id = "fdg_edge_f1"
        name = "FDG依赖边F1"
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return MetricResult(
        metric_id=metric_id,
        name=name,
        value=round(f1, 4),
        unit="ratio",
        level="task",
        passed=math.isclose(f1, 1.0, abs_tol=1e-6),
    )


def first_validation_pass(run_dir: Path) -> MetricResult:
    path = run_dir / "validation_initial.json"
    ok = False
    if path.exists():
        data = _load_json(path)
        ok = bool(data.get("ok"))
    else:
        report = run_dir / "validation_report.json"
        if report.exists():
            ok = bool(_load_json(report).get("ok"))
    return MetricResult(
        metric_id="first_validation_pass",
        name="建模规范首次校验通过率",
        value=1.0 if ok else 0.0,
        unit="ratio",
        level="task",
        passed=ok,
    )


_MEASURE_TOOLS = (
    "measure_disc_dimensions", "measure_fir_tree_slot_profile",
    "count_fir_tree_slots", "measure_hole_pattern",
)


def _measured_from_dir(run_dir: Path) -> dict[str, Any]:
    measured: dict[str, Any] = {}
    for tool in _MEASURE_TOOLS:
        try:
            result = call_mcp_tool(tool, {"base_dir": str(run_dir)})
            if isinstance(result, dict):
                measured.update({
                    k: v for k, v in result.items()
                    if isinstance(v, (int, float)) and k not in ("ok",)
                })
        except Exception:  # noqa: BLE001
            continue
    return measured


_PARAM_TO_MEASURE = {
    "od_mm": ("outer_diameter_mm", "abs"),
    "bore_mm": ("bore_diameter_mm", "abs"),
    "thick_mm": ("axial_thickness_mm", "abs"),
    "hub_mm": ("hub_half_thickness_mm", "abs"),
    "rim_mm": ("rim_half_thickness_mm", "abs"),
    "depth_mm": ("slot_depth_mm", "abs"),
    "throat_half_width_mm": ("throat_half_width_mm", "abs"),
    "slots": ("count", "count"),
    "holes": ("holes", "count"),
    "pcd_mm": ("pcd_mm", "abs"),
    "hdia_mm": ("hdia_mm", "abs"),
}


def parameter_extraction_accuracy(
    expected: dict[str, Any],
    measured: dict[str, Any],
    *,
    length_tolerance: float = 0.05,
) -> MetricResult | None:
    """用户需求参数 vs 模型实测值的提取一致率（论文“参数识别准确率”口径）。"""
    checked = 0
    matched = 0
    detail = []
    for key, expected_value in expected.items():
        rule = _PARAM_TO_MEASURE.get(key)
        if rule is None or expected_value is None:
            continue
        measured_key, kind = rule
        actual = measured.get(measured_key)
        if actual is None:
            continue
        checked += 1
        if kind == "count":
            ok = int(actual) == int(expected_value)
        else:
            ok = abs(float(actual) - float(expected_value)) <= length_tolerance
        detail.append({"param": key, "expected": expected_value,
                       "actual": actual, "ok": ok})
        if ok:
            matched += 1
    if not checked:
        return None
    return MetricResult(
        metric_id="parameter_extraction_accuracy",
        name="参数识别准确率",
        value=round(matched / checked, 4),
        unit="ratio",
        level="task",
        passed=matched == checked,
        notes=json.dumps(detail, ensure_ascii=False),
    )


def parameter_extraction_consistency_vs_golden(
    run_dir: Path,
    gold_dir: Path,
    expected_params: dict[str, Any],
    *,
    length_tolerance: float = 0.05,
) -> MetricResult | None:
    """Compare actual measured parameters against golden measured parameters.

    This is used by the semantics suite only. It avoids comparing raw prompt
    parameters whose definition can differ from the deterministic golden CAD
    geometry (e.g. nominal slot depth vs profile radial span, inconsistent
    axial-thickness/half-thickness task text).
    """
    measured = _measured_from_dir(run_dir)
    gold_measured = _measured_from_dir(gold_dir)
    detail: list[dict[str, Any]] = []
    checked = 0
    matched = 0
    for key, raw_value in expected_params.items():
        if raw_value is None:
            continue
        rule = _PARAM_TO_MEASURE.get(key)
        if rule is None:
            continue
        measured_key, kind = rule
        expected = gold_measured.get(measured_key)
        actual = measured.get(measured_key)
        if expected is None or actual is None:
            continue
        checked += 1
        if kind == "count":
            ok = int(actual) == int(expected)
        else:
            ok = abs(float(actual) - float(expected)) <= length_tolerance
        detail.append({
            "param": key,
            "expected": expected,
            "actual": actual,
            "ok": ok,
        })
        if ok:
            matched += 1
    if not checked:
        return None
    return MetricResult(
        metric_id="parameter_extraction_accuracy",
        name="参数识别准确率",
        value=round(matched / checked, 4),
        unit="ratio",
        level="task",
        passed=matched == checked,
        notes=json.dumps(detail, ensure_ascii=False),
    )


class SemanticMetricsComputer:
    def compute(
        self,
        *,
        run_dir: Path,
        task_spec: TaskSpec,
        run_result: RunResult,
        config: ExperimentConfig,
    ) -> list[MetricResult]:
        run_ir_path = run_dir / "raw_fixed.json"
        ref_ir_path = task_spec.gold.canonical_ir_path
        if not run_ir_path.exists() or not ref_ir_path.exists():
            return [MetricResult(
                metric_id="semantic_missing_artifacts",
                name="语义指标",
                value=False,
                passed=False,
                notes="缺少 raw_fixed.json 或 golden canonical_ir.json",
            )]
        run_ir = _load_json(run_ir_path)
        ref_ir = _load_json(ref_ir_path)
        metrics = [
            parameter_accuracy(
                _params_from_ir(ref_ir),
                _params_from_ir(run_ir),
                tolerance=config.eval.length_tolerance_mm,
            ),
        ]
        extraction = parameter_extraction_accuracy(
            task_spec.normalized_params,
            _measured_from_dir(run_dir),
            length_tolerance=config.eval.length_tolerance_mm,
        )
        if extraction is not None:
            metrics.append(extraction)
        metrics += [
            fdg_f1(_ir_nodes(ref_ir), _ir_nodes(run_ir), kind="node"),
            fdg_f1(_ir_nodes(ref_ir), _ir_nodes(run_ir), kind="edge"),
            first_validation_pass(run_dir),
        ]
        return metrics
