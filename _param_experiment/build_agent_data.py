"""多 Agent 训练数据构建：从确定性参数化模板 llm_raw 反推 L1/A/B/C 训练样本。

用户需求：仅用 llm_raw 训练不够，需同时训练 A/B/C 三 agent（+ L1 路由）：
  - L1_routing   需求 → DialectSelectionPlan（路由决策，含方言目录）
  - A_design     需求 → AgentDesignPlan（gcad_skeleton 骨架 + profiles 参数声明）
  - B_disc_profile  盘体参数 → 12 点 R-Z 盘体轮廓
  - C_slot_profile  榫槽参数 → 2×(2+4n+3) 点榫槽轮廓

每个样本保存完整 (system_prompt, user_input, gold_output)，system 复用 agentic_l2 的
AGENT_A_SYSTEM/_DISC_SYSTEM/_SLOT_SYSTEM 与 L1 的 LEVEL1_ROUTING_SYSTEM_PROMPT。

独立于主流程/src（只 import 常量，不调用）；LLM 无关（确定性反推）。

用法:
  .conda/python.exe _param_experiment/build_agent_data.py            # 全量候选
  .conda/python.exe _param_experiment/build_agent_data.py --family D15 --limit 2
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
DATASETS = _HERE / "output" / "datasets" / "agent_data"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from agentic_l2 import (  # noqa: E402
    AGENT_A_SYSTEM, _DISC_SYSTEM, _SLOT_SYSTEM, _append_parametric_block,
)
from param_templates import build, plan  # noqa: E402
from seekflow_engineering_tools.generative_cad.skills.orchestrator import (  # noqa: E402
    build_level1_routing_prompt,
)
from seekflow_engineering_tools.generative_cad.skills.prompts import (  # noqa: E402
    LEVEL1_ROUTING_SYSTEM_PROMPT,
)

# 模板 kind_hint → agentic_l2 契约（assemble 的 _KIND_HINT_TO_KIND 路由）
_KIND_HINT_MAP = {"axisymmetric_disc": "turbine_disc", "fir_tree_slot_cutter": "fir_tree_cutter"}
SLOT_CATS = ("slot", "coupled", "complex_rim")


def _disc_comp_id(llm_raw: dict) -> str:
    for c in llm_raw.get("components", []):
        kh = c.get("kind_hint") or ""
        if "disc" in kh:
            return c.get("id")
    return "disc_body"


def _points_of(llm_raw: dict, comp_id: str) -> list:
    for n in llm_raw.get("nodes", []):
        if n.get("op") == "add_polyline" and n.get("component") == comp_id:
            return n.get("params", {}).get("points", [])
    return []


def _profile_stations(llm_raw: dict) -> list:
    """axisym 盘体的盘体轮廓 = revolve_profile 的 profile_stations（无 add_polyline）。"""
    for n in llm_raw.get("nodes", []):
        if n.get("op") == "revolve_profile":
            st = n.get("params", {}).get("profile_stations")
            if isinstance(st, list):
                return st
    return []


def _slot_comp_id(llm_raw: dict) -> str:
    for c in llm_raw.get("components", []):
        kh = c.get("kind_hint") or ""
        if "slot" in kh or "cutter" in kh:
            return c.get("id")
    return "slot_cutter"


def build_samples(cand: dict) -> dict:
    """单个候选 → {task_id, category, family, design_id?, samples:[...]}。"""
    cat = cand.get("category", "slot")
    params = cand.get("params", {})
    text = cand.get("text", "")
    llm_raw = build({**params, "category": cat})
    samples = []
    # L1 路由
    l1 = build_level1_routing_prompt(text)
    samples.append({
        "agent_role": "L1_routing",
        "system_prompt": l1.get("system", LEVEL1_ROUTING_SYSTEM_PROMPT),
        "user_input": l1.get("user", ""),
        "gold_output": {"route_decision": "generative_cad_ir",
                        "selected_dialects": llm_raw.get("selected_dialects", []),
                        "selected_domains": None},
    })
    # Agent A 规划（原生 plan()：骨架 + profiles 参数声明）
    ap = plan({**params, "category": cat})
    user_a = text + _append_parametric_block(text)
    samples.append({
        "agent_role": "A_design",
        "system_prompt": AGENT_A_SYSTEM,
        "user_input": user_a,
        "gold_output": ap,
    })
    # Agent B 盘体轮廓（原生 plan 的 disc 参数）
    disc_prof = next(p for p in ap["profiles"] if p["kind"] == "disc")
    disc_pid, disc_params = disc_prof["profile_id"], disc_prof["params"]
    user_b = (f"请为轮廓 [{disc_pid}]（kind=disc）从参数生成精确闭合轮廓点。\n"
              f"轮廓参数: {', '.join(f'{k}={v}' for k, v in sorted(disc_params.items()))}\n"
              f"需求相关: {text[:800]}")
    if cat in SLOT_CATS:
        # 榫槽类：盘体轮廓 = sketch_profile add_polyline 12 点
        b_gold = {"profile_id": disc_pid, "kind": "disc",
                  "points": _points_of(llm_raw, _disc_comp_id(llm_raw))}
    else:
        # axisym 类：盘体轮廓 = revolve_profile profile_stations（无 add_polyline）
        b_gold = {"profile_id": disc_pid, "kind": "disc",
                  "points": _profile_stations(llm_raw)}
    samples.append({
        "agent_role": "B_disc_profile",
        "system_prompt": _DISC_SYSTEM,
        "user_input": user_b,
        "gold_output": b_gold,
    })
    # Agent C 榫槽轮廓（仅含榫槽类，原生 plan 的 slot 参数）
    if cat in SLOT_CATS:
        slot_prof = next(p for p in ap["profiles"] if p["kind"] == "slot")
        slot_pid, slot_params = slot_prof["profile_id"], slot_prof["params"]
        user_c = (f"请为轮廓 [{slot_pid}]（kind=slot）从参数生成精确闭合轮廓点。\n"
                  f"轮廓参数: {', '.join(f'{k}={v}' for k, v in sorted(slot_params.items()))}\n"
                  f"需求相关: {text[:800]}")
        slot_comp = _slot_comp_id(llm_raw)
        samples.append({
            "agent_role": "C_slot_profile",
            "system_prompt": _SLOT_SYSTEM,
            "user_input": user_c,
            "gold_output": {"profile_id": slot_pid, "kind": "slot",
                            "points": _points_of(llm_raw, slot_comp)},
        })
    return {"task_id": cand.get("task_id"), "category": cat,
            "family": cand.get("family"), "samples": samples}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="多 Agent 训练数据构建")
    ap.add_argument("--family", default=None, help="只处理指定设计族")
    ap.add_argument("--limit", type=int, default=None, help="最多处理 N 个候选")
    args = ap.parse_args(argv)

    cand_doc = json.loads((_HERE / "output" / "datasets" / "candidates.json").read_text(encoding="utf-8"))
    cands = cand_doc.get("candidates", [])
    if args.family:
        cands = [c for c in cands if c.get("family") == args.family]
    if args.limit:
        cands = cands[: args.limit]

    DATASETS.mkdir(parents=True, exist_ok=True)
    from collections import Counter
    role_cnt = Counter()
    written = 0
    for c in cands:
        rec = build_samples(c)
        (DATASETS / f"{rec['task_id']}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        for s in rec["samples"]:
            role_cnt[s["agent_role"]] += 1
        written += 1
    index = {"schema": "agent_data_v1", "generated_at": datetime.now().isoformat(timespec="seconds"),
             "candidates": written, "role_counts": dict(role_cnt)}
    (DATASETS / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"多 Agent 训练数据 -> {DATASETS}  ({written} 候选)")
    for role, n in role_cnt.items():
        print(f"  {role:18s} {n} 样本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
