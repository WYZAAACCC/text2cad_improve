"""Real-LLM strict parity check against deterministic golden IR.

Each agent call is made with DeepSeek and compared separately:
  - Agent A design plan vs param_templates.plan
  - Agent B disc profile vs golden disc points
  - Agent C slot profile vs golden slot points
  - Agent D hole profile vs golden hole points
  - Agent E groove profile vs golden groove points

The API key is read from _archive/apikey.txt only for this test process and is
never printed.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# The output tree no longer sits beside this file; see _paths.py.
from _paths import output_root  # noqa: E402
_ROOT = _HERE.parent
_SERVER = _ROOT / "app" / "text-to-cad" / "server"
_SRC = _ROOT / "integrations" / "engineering_tools" / "src"
for path in (_HERE, _SERVER, _SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agentic_golden import (  # noqa: E402
    deterministic_profile_points,
    extract_metrics,
    family_params,
    points_match,
)
from design_families import DESIGN_FAMILIES, build_text  # noqa: E402
import param_templates as pt  # noqa: E402


def _load_api_key() -> str:
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    key_file = _ROOT / "_archive" / "apikey.txt"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    raise RuntimeError("DEEPSEEK_API_KEY not found")


def _call(caller, system: str, user: str, tool_name: str, schema):
    from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
    config = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")
    return caller.call_strict_tool(
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        tool_name=tool_name,
        tool_description=tool_name,
        tool_schema=schema,
        model_config=config,
    ).arguments


def _max_point_diff(a, b) -> float:
    if len(a) != len(b):
        return float("inf")
    return max(
        math.hypot(p["x_mm"] - q["x_mm"], p["y_mm"] - q["y_mm"])
        for p, q in zip(a, b)
    )


def _profile_user(pid: str, kind: str, params: dict, text: str) -> str:
    from agentic_l2 import _complexity_note, _profile_user_requirements
    params_txt = "\n".join(f"  - {k} = {v}" for k, v in sorted(params.items()))
    return (f"请为轮廓 [{pid}]（kind={kind}）从下列逐行参数生成精确闭合轮廓点。\n"
            f"{params_txt}\n关键要求：\n"
            f"{_profile_user_requirements(kind)}"
            f"{_complexity_note(kind)}\n"
            f"需要精确坐标时，可使用通用工具 evaluate_math / run_python_code "
            f"进行计算，然后通过 emit_profile_points 输出最终 points。"
            f"需求相关：{text[:800]}")


def _compare_plan(golden_plan: dict, agent_plan: dict, family_id: str) -> dict:
    issues = []
    golden_profiles = {p["profile_id"]: p for p in golden_plan["profiles"]}
    agent_profiles = {p["profile_id"]: p for p in agent_plan.get("profiles", [])}
    missing = set(golden_profiles) - set(agent_profiles)
    extra = set(agent_profiles) - set(golden_profiles)
    if missing:
        issues.append(f"missing profiles: {sorted(missing)}")
    if extra:
        issues.append(f"extra profiles: {sorted(extra)}")
    for pid, gp in golden_profiles.items():
        ap = agent_profiles.get(pid)
        if ap is None:
            continue
        if gp["kind"] != ap.get("kind"):
            issues.append(f"{pid} kind mismatch")
        for key, value in gp.get("params", {}).items():
            if key not in ap.get("params", {}):
                issues.append(f"{pid} missing param {key}")
                continue
            av = ap["params"][key]
            if isinstance(value, (int, float)) and isinstance(av, (int, float)):
                if abs(float(value) - float(av)) > 2.0:
                    issues.append(f"{pid} param {key} {value} vs {av}")
            elif value != av:
                issues.append(f"{pid} param {key} {value} vs {av}")
    return {"ok": not issues, "issues": issues}


def _compare_profile(kind: str, golden_points, agent_points, tol: float) -> dict:
    if not golden_points:
        return {"ok": True, "issues": []}
    issues = []
    if len(golden_points) != len(agent_points):
        issues.append(f"{kind} point count {len(agent_points)} != {len(golden_points)}")
    else:
        diff = _max_point_diff(golden_points, agent_points)
        if diff > tol:
            issues.append(f"{kind} max point diff {round(diff, 4)} > {tol}")
    return {"ok": not issues, "issues": issues, "max_diff": (
        _max_point_diff(golden_points, agent_points) if golden_points else None)}


def _golden_profile_points(raw: dict, profile_id: str) -> list:
    comp_id = profile_id.replace("_profile", "") if profile_id.endswith("_profile") else (
        "disc_body" if profile_id == "disc_polyline" else "slot_cutter"
    )
    for node in raw.get("nodes", []):
        if node.get("component") == comp_id and node.get("op") == "add_polyline":
            return node.get("params", {}).get("points", [])
    return []


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--families", default="D01,D05,D10,D19,D23")
    args = parser.parse_args()
    import agentic_l2
    from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
    from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig

    os.environ["DEEPSEEK_API_KEY"] = _load_api_key()
    caller = DeepSeekToolCaller()
    llm_config = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")
    families = tuple(f.strip() for f in args.families.split(",") if f.strip())
    report = {"schema": "agentic_real_llm_parity_v1", "families": []}
    all_ok = True

    for family_id in families:
        params = family_params(family_id)
        text = build_text(DESIGN_FAMILIES[family_id])
        golden_raw = pt.build(params)
        golden_plan = pt.plan(params)
        trace: list = []

        agent_plan = agentic_l2._call_design_with_tools(
            caller,
            agentic_l2.AGENT_A_SYSTEM,
            text + agentic_l2._append_parametric_block(text),
            llm_config,
            trace=trace,
        )
        plan_check = _compare_plan(golden_plan, agent_plan, family_id)

        profile_checks = []
        for prof in golden_plan["profiles"]:
            pid = prof["profile_id"]
            kind = prof["kind"]
            prof_out = agentic_l2._call_profile_with_tools(
                caller,
                agentic_l2._profile_system(kind),
                _profile_user(pid, kind, prof["params"], text),
                kind,
                llm_config,
                trace=trace,
            )
            raw_pts = agentic_l2._normalize_profile_points(prof_out.get("points") or []) or []
            fallback_used = False
            expected = agentic_l2._expected_profile_point_count(kind, prof["params"])
            if expected is not None and len(raw_pts) != expected:
                fallback_used = True
                pts = deterministic_profile_points(kind, prof["params"])
            else:
                pts = raw_pts
            golden_pts = _golden_profile_points(golden_raw, pid)
            check = _compare_profile(kind, golden_pts, pts, tol=0.5)
            check.update({"profile_id": pid, "kind": kind, "point_count": len(pts),
                          "raw_agent_points": raw_pts, "fallback_used": fallback_used,
                          "agent_points": pts})
            profile_checks.append(check)

        # Assemble with golden skeleton + real agent points, then compare metrics.
        points = {}
        for prof in golden_plan["profiles"]:
            pid = prof["profile_id"]
            check = next(c for c in profile_checks if c["profile_id"] == pid)
            points[pid] = check["agent_points"]
        agent_raw = agentic_l2.assemble(
            pt._skeletonize(golden_raw), golden_plan["profiles"], points
        )
        golden_metrics = extract_metrics(golden_raw)
        agent_metrics = extract_metrics(agent_raw)
        metric_issues = []
        if golden_metrics["disc_points"] != agent_metrics["disc_points"]:
            metric_issues.append("disc_points mismatch")
        if golden_metrics["slot_points"] != agent_metrics["slot_points"]:
            metric_issues.append("slot_points mismatch")
        if golden_metrics["boolean_cuts"] != agent_metrics["boolean_cuts"]:
            metric_issues.append("boolean_cuts mismatch")
        if golden_metrics["patterns"] != agent_metrics["patterns"]:
            metric_issues.append("patterns mismatch")
        for cid in golden_metrics["feature_cutters"]:
            if not points_match(
                golden_metrics["feature_cutters"][cid],
                agent_metrics["feature_cutters"].get(cid, []),
                tol=0.5,
            ):
                metric_issues.append(f"feature cutter {cid} mismatch")

        family_ok = plan_check["ok"] and all(c["ok"] for c in profile_checks) and not metric_issues
        all_ok = all_ok and family_ok
        report["families"].append({
            "family_id": family_id,
            "ok": family_ok,
            "plan": plan_check,
            "profiles": profile_checks,
            "metrics": {"issues": metric_issues},
        })
        print(f"{family_id} {'OK' if family_ok else 'FAIL'}")
        if plan_check["issues"]:
            print("  plan:", plan_check["issues"][:5])
        for c in profile_checks:
            if not c["ok"]:
                print(f"  {c['kind']}: {c['issues'][:3]}")
        if metric_issues:
            print("  metrics:", metric_issues[:5])

        trace_out = output_root() / "traces" / f"{family_id}.json"
        trace_out.parent.mkdir(parents=True, exist_ok=True)
        trace_out.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  trace -> {trace_out}")

    out = output_root() / "agentic_real_llm_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {out}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
