"""Tests for sub-experiment suites (no LLM/API calls)."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..aggregate import load_tasks
from ..config import default_experiment_config
from ..suites import direct_base, infeasible, methods, regen, semantics, tools


def _tasks():
    return load_tasks(default_experiment_config())


def test_regen_builds_800():
    tasks = _tasks()
    items = regen.build_tasks(default_experiment_config(), seed=0)
    assert len(items) == 800
    assert Counter(i["category"] for i in items) == {
        "single": 200, "double": 200, "triple_five": 200, "cross_feature": 200,
    }
    assert len({i["perturbation_id"] for i in items}) == 800


def test_semantics_builds_320():
    tasks = _tasks()
    items = semantics.build_tasks(tasks)
    assert len(items) == 320
    assert Counter(i["category"] for i in items)["baseline"] == 40
    assert len({i["semantic_id"] for i in items}) == 320


def test_tools_builds_160():
    tasks = _tasks()
    items = tools.build_tasks(tasks)
    assert len(items) == 160
    assert Counter(i["category"] for i in items) == {
        "single": 40, "multi": 40, "anomaly": 40, "new": 40,
    }


def test_infeasible_builds_120():
    tasks = _tasks()
    items = infeasible.build_tasks(tasks)
    assert len(items) == 120
    assert Counter(i["category"] for i in items) == {
        "hole_out_of_bounds": 24, "slot_pitch_insufficient": 24,
        "slot_depth_over_rim": 24, "fillet_unconstructable": 24,
        "hard_constraint_conflict": 24,
    }


def test_aggregates_shape():
    regen_rows = regen.aggregate([
        {"category": "single", "margin_group": "far", "regenerated_ok": True,
         "quality_ok": True},
        {"category": "single", "margin_group": "near", "regenerated_ok": False,
         "quality_ok": False},
    ])
    assert regen_rows["rows"][-1]["regen_success"] == 0.5

    sem = semantics.aggregate([
        {"param_consistent": True, "fdg_isomorphic": True, "engineering_ok": True},
        {"param_consistent": False, "fdg_isomorphic": False, "engineering_ok": False},
    ])
    assert sem["engineering_success_rate"] == 0.5

    tool_rows = tools.aggregate([
        {"interface": "fixed", "selected": {"a"}, "expected": {"a"},
         "binding_ok": True, "multi_complete": True, "result_ok": True,
         "new_tool_called": False},
        {"interface": "mcp_agent", "selected": {"b"}, "expected": {"a"},
         "binding_ok": False, "multi_complete": False, "result_ok": False,
         "new_tool_called": False},
    ])
    by_iface = {r["interface"]: r for r in tool_rows["rows"]}
    assert by_iface["fixed"]["tool_selection_f1"] == 1.0
    assert by_iface["mcp_agent"]["tool_selection_f1"] == 0.0


def test_method_specs_registry():
    specs = methods.method_specs()
    ids = {s.method_id for s in specs}
    assert {"base_coder", "qwen72b", "deepseek_r1_distill", "llama70b",
            "cad_rag", "aerodisk_llm"} <= ids


def test_direct_base_aggregate():
    from ..schemas import MetricResult, RunResult, RunStatus
    ok_metric = MetricResult(metric_id="direct_engineering_ok",
                             name="x", value=True, passed=True)
    agg = direct_base.aggregate([
        RunResult(run_id="r1", method_id="direct_base", task_id="T01", seed=0,
                  status=RunStatus.COMPLETED, ok=True, metrics=[ok_metric]),
        RunResult(run_id="r2", method_id="direct_base", task_id="T01", seed=1,
                  status=RunStatus.FAILED, ok=False),
    ])
    assert agg["cad_pass1"] == 0.5
    assert agg["engineering_pass1_bbox"] == 0.5


def test_record_format_and_collection(tmp_path):
    from ..suites.base import stamp_record, write_collection
    rec = stamp_record({"task_id": "T01", "value": 1}, "regen", "regen_v1")
    assert rec["record_id"].startswith("regen_")
    assert rec["collected_at"]
    assert rec["schema_version"] == "regen_v1"

    paths = write_collection(
        tmp_path / "col", "exp1", "regen_v1", [rec],
        {"rows": [{"category": "single", "regen_success": 1.0}]},
        prefix="regen",
    )
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["experiment_id"] == "exp1"
    assert manifest["record_count"] == 1
    assert manifest["record_ids"] == [rec["record_id"]]
    records = json.loads(paths["records"].read_text(encoding="utf-8"))
    assert records[0]["record_id"] == rec["record_id"]
    assert paths["report"].exists()


def test_fdg_edge_normalizes_ids_and_producer_node():
    from ..metrics.semantics import fdg_f1
    ref = [
        {"id": "a", "component": "disc_body", "dialect": "sketch_profile",
         "op": "create_2d_sketch", "phase": "sketch", "inputs": []},
        {"id": "b", "component": "disc_body", "dialect": "sketch_profile",
         "op": "add_polyline", "phase": "profile",
         "inputs": [{"producer_node": "a", "output": "sketch"}]},
    ]
    act = [
        {"id": "x", "component": "turbine_disc", "dialect": "sketch_profile",
         "op": "create_2d_sketch", "phase": "sketch", "inputs": []},
        {"id": "y", "component": "turbine_disc", "dialect": "sketch_profile",
         "op": "add_polyline", "phase": "profile",
         "inputs": [{"node": "x", "output": "sketch"}]},
    ]
    node = fdg_f1(ref, act, kind="node")
    edge = fdg_f1(ref, act, kind="edge")
    assert node.value == 1.0
    assert edge.value == 1.0


def test_openai_client_passes_seed(monkeypatch):
    from types import SimpleNamespace
    from ..llm import OpenAICompatToolClient
    from ..config import LlmConfig

    captured = {}

    class _FakeChat:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(tool_calls=[SimpleNamespace(
                id="c", type="function",
                function=SimpleNamespace(name="t", arguments="{}"))])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)],
                                   id="resp_1",
                                   usage=SimpleNamespace(
                                       prompt_tokens=1, completion_tokens=1,
                                       total_tokens=2))

    class _FakeOpenAI:
        def __init__(self, *a, **k):
            self.chat = SimpleNamespace(completions=_FakeChat())

    import openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    client = OpenAICompatToolClient()
    llm = LlmConfig(seed=7, temperature=0.3, top_p=0.9)
    client.call_strict_tool(
        messages=[{"role": "user", "content": "x"}],
        tool_name="t", tool_description="t",
        tool_schema={"type": "object"}, config=llm,
    )
    assert captured.get("seed") == 7
    assert captured.get("temperature") == 0.3
    assert captured.get("top_p") == 0.9


def test_openai_client_handles_multiple_tool_calls(monkeypatch):
    from types import SimpleNamespace
    from ..llm import OpenAICompatToolClient
    from ..config import LlmConfig

    captured = {}

    class _FakeChat:
        def create(self, **kwargs):
            captured.update(kwargs)
            calls = [
                SimpleNamespace(id="c1", type="function",
                                function=SimpleNamespace(name="other", arguments="{}")),
                SimpleNamespace(id="c2", type="function",
                                function=SimpleNamespace(name="t", arguments='{"a":1}')),
            ]
            message = SimpleNamespace(tool_calls=calls)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)],
                                   id="resp_1",
                                   usage=SimpleNamespace(
                                       prompt_tokens=1, completion_tokens=1,
                                       total_tokens=2))

    class _FakeOpenAI:
        def __init__(self, *a, **k):
            self.chat = SimpleNamespace(completions=_FakeChat())

    import openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    result = OpenAICompatToolClient().call_strict_tool(
        messages=[{"role": "user", "content": "x"}],
        tool_name="t", tool_description="t",
        tool_schema={"type": "object"}, config=LlmConfig(),
    )
    assert result.arguments == {"a": 1}


def test_parameter_extraction_accuracy_maps_measured():
    from ..metrics.semantics import parameter_extraction_accuracy
    metric = parameter_extraction_accuracy(
        {"od_mm": 500, "bore_mm": 120, "thick_mm": 76},
        {"outer_diameter_mm": 500.0, "bore_diameter_mm": 120.0,
         "axial_thickness_mm": 76.0},
        length_tolerance=0.05,
    )
    assert metric is not None
    assert metric.value == 1.0
    bad = parameter_extraction_accuracy(
        {"od_mm": 500, "bore_mm": 120, "thick_mm": 76},
        {"outer_diameter_mm": 510.0, "bore_diameter_mm": 120.0,
         "axial_thickness_mm": 76.0},
        length_tolerance=0.05,
    )
    assert abs(bad.value - 2 / 3) < 1e-4


def test_infeasible_precheck_rejects_categories():
    from ..suites import infeasible
    tasks = _tasks()
    items = infeasible.build_tasks(tasks)
    for item in items:
        rejected, reasons = infeasible.feasibility_precheck(item)
        assert rejected, item["category"]
        assert reasons


def test_new_tools_all_implemented_on_golden():
    from ..suites.tools import _run_new_tool, _new_tool_catalog
    base = str(Path(__file__).resolve().parents[1] / "output" / "golden" / "T01")
    if not (Path(base) / "raw_fixed.json").exists():
        return
    feature_only = {"count_cooling_holes", "count_lightening_holes", "count_grooves",
                    "measure_groove_depth", "measure_groove_width",
                    "measure_slot_distribution_radius",
                    "measure_slot_circumferential_pitch"}
    for tool in _new_tool_catalog():
        res = _run_new_tool(tool["name"], base)
        assert isinstance(res, dict) and "value" in res, tool["name"]
        if tool["name"] not in feature_only:
            assert res["ok"], tool["name"]
