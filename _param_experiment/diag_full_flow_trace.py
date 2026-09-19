"""端到端真实 LLM trace 诊断：完整 run_agentic_l2 + 参数化基准对比。

监控整套 agent 流程（Agent A → Worker → assemble）的过程数据，落盘
out_dir/agent_trace.json，并对比每个 profile 的参数与最终轮廓点。

用法（API key 从 _archive/apikey.txt 读取）:
  .conda\\python.exe -u _param_experiment/diag_full_flow_trace.py --families D10
"""
from __future__ import annotations

import argparse
import copy
import json
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

from agentic_golden import extract_metrics, family_params, points_match  # noqa: E402
from design_families import DESIGN_FAMILIES, build_text  # noqa: E402
import param_templates as pt  # noqa: E402
from verify_agentic_real_llm import _compare_plan, _golden_profile_points  # noqa: E402


def _load_api_key() -> str:
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    key_file = _ROOT / "_archive" / "apikey.txt"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    raise RuntimeError("DEEPSEEK_API_KEY not found")


def _agent_feature_points(raw: dict, profile_id: str) -> list:
    if profile_id == "disc_polyline":
        comp_id = "turbine_disc"
    elif profile_id == "cutter_polyline":
        comp_id = "fir_tree_cutter"
    else:
        comp_id = profile_id.replace("_profile", "")
    for node in raw.get("nodes", []):
        if node.get("component") == comp_id and node.get("op") == "add_polyline":
            return node.get("params", {}).get("points", [])
    return []


def _eval_family(fid: str, agent_raw: dict, out_dir: Path) -> dict:
    """与参数化基准逐项对比单个 agent 输出，返回报告条目。"""
    import agentic_l2
    agent_raw = copy.deepcopy(agent_raw)
    for node in agent_raw.get("nodes", []):
        if node.get("op") == "add_polyline":
            pts = agentic_l2._normalize_profile_points(
                node.get("params", {}).get("points"))
            if pts:
                node.setdefault("params", {})["points"] = pts
    params = family_params(fid)
    text = build_text(DESIGN_FAMILIES[fid])
    golden_raw = pt.build(params)
    golden_plan = pt.plan(params)
    agent_plan = json.loads(
        (out_dir / "agent_a_plan.json").read_text(encoding="utf-8"))
    plan_check = _compare_plan(golden_plan, agent_plan, fid)

    profile_checks = []
    for prof in golden_plan["profiles"]:
        pid = prof["profile_id"]
        golden_pts = _golden_profile_points(golden_raw, pid)
        agent_pts = _agent_feature_points(agent_raw, pid)
        ok = points_match(golden_pts, agent_pts, tol=0.5)
        profile_checks.append({
            "profile_id": pid,
            "kind": prof["kind"],
            "golden_count": len(golden_pts),
            "agent_count": len(agent_pts),
            "ok": ok,
        })

    golden_metrics = extract_metrics(golden_raw)
    agent_metrics = extract_metrics(agent_raw)
    metric_issues = []
    if not points_match(
        golden_metrics["disc_points"], agent_metrics["disc_points"], tol=0.5,
    ):
        metric_issues.append("disc_points mismatch")
    if not points_match(
        golden_metrics["slot_points"], agent_metrics["slot_points"], tol=0.5,
    ):
        metric_issues.append("slot_points mismatch")
    if golden_metrics["boolean_cuts"] != agent_metrics["boolean_cuts"]:
        metric_issues.append("boolean_cuts mismatch")
    for cid in golden_metrics["feature_cutters"]:
        if not points_match(
            golden_metrics["feature_cutters"][cid],
            agent_metrics["feature_cutters"].get(cid, []),
            tol=0.5,
        ):
            metric_issues.append(f"feature cutter {cid} mismatch")

    family_ok = plan_check["ok"] and all(c["ok"] for c in profile_checks) \
        and not metric_issues
    return {
        "family_id": fid,
        "ok": family_ok,
        "plan": plan_check,
        "profiles": profile_checks,
        "metrics": {"issues": metric_issues},
        "trace": str(out_dir / "agent_trace.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--families", default="D10")
    parser.add_argument("--offline", action="store_true",
                        help="只评估已有 llm_raw.json，不再调用 LLM")
    args = parser.parse_args()

    import agentic_l2
    from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
    from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig

    os.environ["DEEPSEEK_API_KEY"] = _load_api_key()
    caller = DeepSeekToolCaller()
    config = LlmModelConfig(model="deepseek-v4-pro",
                            base_url="https://api.deepseek.com/beta")
    families = tuple(f.strip() for f in args.families.split(",") if f.strip())
    report = {"schema": "agentic_full_flow_trace_v1", "families": []}
    all_ok = True

    for fid in families:
        out_dir = output_root() / "full_flow_trace" / fid
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            if args.offline:
                agent_raw = json.loads(
                    (out_dir / "llm_raw.json").read_text(encoding="utf-8"))
            else:
                text = build_text(DESIGN_FAMILIES[fid])
                agent_raw = agentic_l2.run_agentic_l2(
                    text, None, caller=caller, llm_model_config=config,
                    out_dir=out_dir,
                )
            entry = _eval_family(fid, agent_raw, out_dir)
        except Exception as exc:  # noqa: BLE001
            entry = {"family_id": fid, "ok": False,
                     "error": f"{type(exc).__name__}: {str(exc)[:500]}"}
        all_ok = all_ok and bool(entry["ok"])
        report["families"].append(entry)
        out = output_root() / "full_flow_trace_report.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"{fid} {'OK' if entry['ok'] else 'FAIL'}")
        if entry.get("error"):
            print("  error:", entry["error"][:300])
        if entry.get("plan", {}).get("issues"):
            print("  plan:", entry["plan"]["issues"][:8])
        for c in entry.get("profiles") or []:
            if not c["ok"]:
                print(f"  {c['profile_id']} {c['kind']}: "
                      f"count {c['golden_count']} vs {c['agent_count']}")
        if entry.get("metrics", {}).get("issues"):
            print("  metrics:", entry["metrics"]["issues"][:5])
        print(f"  trace -> {out_dir / 'agent_trace.json'}")

    out = output_root() / "full_flow_trace_report.json"
    print(f"report -> {out}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
