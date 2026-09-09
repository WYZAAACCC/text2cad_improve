"""Agent A plan 后验证与权威参数一致性测试。"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

_HERE = Path(__file__).resolve().parent
_SERVER = _HERE.parent / "app" / "text-to-cad" / "server"
for _p in (_HERE, _SERVER):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import agentic_l2  # noqa: E402
from agentic_golden import authoritative_profile_params, family_params  # noqa: E402
from design_families import DESIGN_FAMILIES, build_text  # noqa: E402
import param_templates as pt  # noqa: E402


def _golden_grooves(family_id: str) -> list:
    plan = pt.plan(family_params(family_id))
    return [p["params"] for p in plan["profiles"]
            if p["kind"] == "groove" and "rimslot" not in p["profile_id"]]


@pytest.mark.parametrize(
    "family_id", ["D10", "D11", "D12", "D13", "D14", "D23"])
def test_authoritative_groove_params_match_golden(family_id):
    text = build_text(DESIGN_FAMILIES[family_id])
    auth = authoritative_profile_params(text)
    assert auth.get("grooves"), family_id
    golden = _golden_grooves(family_id)
    assert len(auth["grooves"]) == len(golden), family_id
    for got, exp in zip(auth["grooves"], golden):
        for key, value in exp.items():
            assert abs(got[key] - float(value)) < 1e-6, (family_id, key)


@pytest.mark.parametrize(
    "family_id",
    ["D01", "D02", "D03", "D04", "D05", "D07", "D09", "D10", "D11",
     "D12", "D13", "D14", "D15", "D19", "D23"])
def test_golden_plan_passes_validation(family_id):
    text = build_text(DESIGN_FAMILIES[family_id])
    golden = pt.plan(family_params(family_id))
    assert agentic_l2._validate_agent_a_plan(golden, text) == []


def test_observed_bad_groove_params_detected():
    text = build_text(DESIGN_FAMILIES["D10"])
    bad = copy.deepcopy(pt.plan(family_params("D10")))
    groove = next(p for p in bad["profiles"] if p["kind"] == "groove")
    groove["params"].update({
        "inner_radius_mm": 176.0,
        "outer_radius_mm": 204.0,
        "z_base_mm": -5.0,
        "depth_mm": 10.0,
    })
    issues = agentic_l2._validate_agent_a_plan(bad, text)
    assert issues
    joined = "\n".join(issues)
    assert "inner_radius_mm" in joined
    assert "径向跨度" in joined


def test_extra_slot_profile_rejected_when_not_required():
    text = build_text(DESIGN_FAMILIES["D01"])
    plan = copy.deepcopy(pt.plan(family_params("D01")))
    plan["profiles"].append({
        "profile_id": "cutter_polyline", "kind": "slot",
        "params": {"teeth_count": 2, "slot_depth_mm": 20.0},
    })
    issues = agentic_l2._validate_agent_a_plan(plan, text)
    assert any("slot profile" in s for s in issues)


def test_groove_shape_issue_catches_bad_y():
    params = {"inner_radius_mm": 190.0, "outer_radius_mm": 204.0,
              "z_base_mm": -25.0, "depth_mm": 10.0}
    bad = [{"x_mm": 190, "y_mm": 0}, {"x_mm": 204, "y_mm": 0},
           {"x_mm": 204, "y_mm": -15}, {"x_mm": 190, "y_mm": -15}]
    assert agentic_l2._feature_shape_issue("groove", bad, params)


class _FakeCaller:
    def call_with_tools(self):
        pass


def test_design_loop_retries_after_validation_failure(monkeypatch):
    import openai

    text = build_text(DESIGN_FAMILIES["D10"])
    valid = pt.plan(family_params("D10"))
    bad = copy.deepcopy(valid)
    groove = next(p for p in bad["profiles"] if p["kind"] == "groove")
    groove["params"].update({
        "inner_radius_mm": 192.0,
        "outer_radius_mm": 202.0,
        "z_base_mm": 16.0,
        "depth_mm": 14.0,
    })

    class _FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            messages = kwargs.get("messages", [])
            corrected = any(
                isinstance(m.get("content"), str)
                and "Agent A 参数校验未通过" in m["content"]
                for m in messages
            )
            if self.calls == 1:
                name, plan = "run_python_code", None
            elif corrected:
                name, plan = "emit_design_plan", valid
            else:
                name, plan = "emit_design_plan", bad
            message = SimpleNamespace(tool_calls=[SimpleNamespace(
                id="call_1",
                type="function",
                function=SimpleNamespace(
                    name=name,
                    arguments=json.dumps(plan, ensure_ascii=False) if plan else '{"code": "print(1)"}'),
            )])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class _FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    config = SimpleNamespace(model="test", base_url="http://x",
                             timeout_s=10, temperature=0.3)
    trace: list = []
    plan_out = agentic_l2._call_design_with_tools(
        _FakeCaller(),
        agentic_l2.AGENT_A_SYSTEM,
        text + agentic_l2._append_parametric_block(text),
        config,
        trace=trace,
    )
    groove = next(p for p in plan_out["profiles"] if p["kind"] == "groove")
    assert groove["params"]["inner_radius_mm"] == 190.0
    assert any(e.get("stage") == "design_validation" for e in trace)


def test_design_loop_accepts_emit_after_two_tool_calls(monkeypatch):
    import openai

    text = build_text(DESIGN_FAMILIES["D10"])
    valid = copy.deepcopy(pt.plan(family_params("D10")))
    bad = copy.deepcopy(pt.plan(family_params("D10")))
    groove = next(p for p in bad["profiles"] if p["kind"] == "groove")
    groove["params"].update({
        "inner_radius_mm": 176.0,
        "outer_radius_mm": 190.0,
        "z_base_mm": -5.0,
        "depth_mm": 10.0,
    })

    class _FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls <= 2:
                name, plan = "run_python_code", None
            else:
                messages = kwargs.get("messages", [])
                corrected = any(
                    isinstance(m.get("content"), str)
                    and "Agent A 参数校验未通过" in m["content"]
                    for m in messages
                )
                name, plan = "emit_design_plan", valid if corrected else bad
            message = SimpleNamespace(tool_calls=[SimpleNamespace(
                id="call_1", type="function",
                function=SimpleNamespace(
                    name=name,
                    arguments=json.dumps(plan) if plan else '{"code": "print(1)"}'),
            )])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class _FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    config = SimpleNamespace(model="test", base_url="http://x",
                             timeout_s=10, temperature=0.3)
    trace: list = []
    plan_out = agentic_l2._call_design_with_tools(
        _FakeCaller(),
        agentic_l2.AGENT_A_SYSTEM,
        text + agentic_l2._append_parametric_block(text),
        config,
        trace=trace,
    )
    groove = next(p for p in plan_out["profiles"] if p["kind"] == "groove")
    assert groove["params"]["inner_radius_mm"] == 190.0  # 校验反馈后采用正确 plan
    tool_events = [e for e in trace if e.get("stage") == "design_tool"]
    assert len(tool_events) == 2
    assert any(e.get("stage") == "design_validation" for e in trace)


def test_eval_math_tool_rejects_multistatement():
    bad = agentic_l2._eval_math_tool({"expression": "a=1; a+1"})
    assert bad["ok"] is False
    assert "run_python_code" in bad["hint"]
    ok = agentic_l2._eval_math_tool({"expression": "60+80"})
    assert ok["ok"] is True
    assert ok["result"] == 140


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
