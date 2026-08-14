"""LLM 自由选择圆角 — 真实 DeepSeek 测试。

验证：LLM 按 prompt 从候选角表自由选角（点+两条边+半径），
  - 边抄写正确率（feedback 中"邻边/不完全匹配"告警数）
  - 非法 key 数
  - 选角覆盖率（建议角 neck/connector/tip/bottom 是否被选）
  - 圆角执行成功（边数增量合理、无 failures）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "integrations" / "engineering_tools" / "src"
sys.path.insert(0, str(SRC))

import cadquery as cq

from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema

from fir_tree_parametric import FirTreeParams, generate_profile
from fillet_free_select import (build_candidate_table, free_select_schema,
                                build_selection_prompt, resolve_selection)
from fillet_corners import execute_fillets

MODEL_CONFIG = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")


def build_wire(pts):
    wp = cq.Workplane("XY")
    for i, pt in enumerate(pts):
        if i == 0:
            wp = wp.moveTo(pt["x_mm"], pt["y_mm"])
        else:
            wp = wp.lineTo(pt["x_mm"], pt["y_mm"])
    wp = wp.close()
    return wp.wire().val()


def call_llm(prompt: str) -> list:
    caller = DeepSeekToolCaller()
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": "请输出你选择的 fillets。"}]
    r = caller.call_strict_tool(
        messages=messages,
        tool_name="emit_fillets",
        tool_description="Emit freely selected fillet corners (vertex + two edges + radius)",
        tool_schema=to_deepseek_strict_schema(free_select_schema()),
        model_config=MODEL_CONFIG,
    )
    return list(r.arguments.get("fillets", []))


def make_params(n: int) -> FirTreeParams:
    return FirTreeParams(
        teeth_count=n, slot_depth_mm=26,
        tooth_height_mm=[7 - i * 0.8 for i in range(n)], tooth_thickness_mm=[2] * n,
        top_flank_angle_deg=[66.7] * n, under_flank_angle_deg=[60] * n,
        neck_half_width_mm=[2.6 - i * 0.2 for i in range(n + 1)], neck_platform_mm=2.0,
        bottom_half_width_mm=4.0, bottom_platform_mm=2.0, bottom_flare_angle_deg=60,
    )


def main():
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    os.environ["DEEPSEEK_API_KEY"] = key

    print("=== LLM 自由选择圆角 — 真实 DeepSeek 测试 ===\n")
    for n in (2, 3):
        p = make_params(n)
        pts = generate_profile(p)
        cands = build_candidate_table(pts, n)
        prompt = build_selection_prompt(cands, n)

        try:
            llm = call_llm(prompt)
        except Exception as e:
            print(f"[{n}齿] LLM 调用失败: {e}")
            continue

        # 统计 LLM 原始输出
        print(f"[{n}齿] LLM 原始输出 {len(llm)} 条:")
        for f in llm:
            print(f"  vertex={f.get('vertex'):18s} edge_a={f.get('edge_a')} edge_b={f.get('edge_b')} r={f.get('radius_mm')}")

        corners, llm_out, feedback = resolve_selection(cands, llm)
        n_bad_key = sum(1 for x in feedback if "未知顶点" in x)
        n_bad_edge = sum(1 for x in feedback if "邻边" in x)
        n_dup = sum(1 for x in feedback if "重复" in x)

        selected_roles = [c["role"] for c in corners]
        # 建议角覆盖率：neck/connector/tip/bottom 各角色被选数
        from collections import Counter
        role_cnt = Counter(selected_roles)

        # 执行圆角
        wire = build_wire(pts)
        n0 = len(list(wire.Edges()))
        fails = {}
        fw = execute_fillets(wire, corners, llm_out, n, pts, failures=fails)
        n1 = len(list(fw.Edges()))

        print(f"\n[结果] 解析: 有效角={len(corners)}/{len(llm)} 非法key={n_bad_key} 边错={n_bad_edge} 重复={n_dup}")
        print(f"  角色分布: {dict(role_cnt)}")
        print(f"  圆角: {n0} -> {n1} 边 (+{n1 - n0}), failures={fails}")
        if feedback:
            print(f"  feedback: {feedback}")
        print()


if __name__ == "__main__":
    main()
