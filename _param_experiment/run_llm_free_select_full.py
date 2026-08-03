"""LLM 全程模拟真实运行：LLM 生成轮廓 → 程序验证/修复 → LLM 自由选圆角 → 执行 → 绘制。

每组合流程（模拟真实生产链路）：
  1. LLM 生成榫槽轮廓点（build_prompt v10/v11 + call_llm_retry 精炼）
  2. 若 LLM 点与确定性 GT 不一致（max_dx≥0.1）→ 回退 GT（模拟修复失败兜底），标注偏差
  3. 基于最终轮廓点建候选角表 → prompt 告诉 LLM 选哪些角
  4. LLM 自由选择 {点+两条边+半径} → resolve_selection 解析校验 → execute_fillets 圆角
  5. 绘制：原始轮廓 | 圆角后（红点=LLM 选中的角），真实圆弧采样

产物：output/llm_free_select_full/
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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

import cadquery as cq

from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema

from fir_tree_parametric import generate_profile
from llm_slot_iteration import call_llm_retry, build_prompt, make_combo
from fillet_free_select import (build_candidate_table, build_selection_prompt,
                                free_select_schema, resolve_selection)
from fillet_corners import execute_fillets
from plot_fillet_show import sample_edge

OUT = Path(__file__).resolve().parent / "output" / "llm_free_select_full"
OUT.mkdir(parents=True, exist_ok=True)

MODEL_CONFIG = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")
API_KEY_FILE = ROOT / "_archive" / "apikey.txt"

# (组合名, prompt版本, 标签)
COMBOS = [
    ("T02_2tooth_equal", "v10", "2齿标准"),
    ("T03_3tooth_standard", "v10", "3齿标准"),
    ("T04_4tooth", "v10", "4齿"),
    ("T06_steep_flank", "v11", "陡齿面75°"),
    ("T07_gentle_flank", "v11", "缓齿面50°"),
    ("T08_large_teeth", "v10", "大齿高"),
]


def call_llm_fillet(prompt: str) -> list:
    caller = DeepSeekToolCaller()
    messages = [{"role": "system", "content": prompt},
                {"role": "user", "content": "请输出你选择的 fillets。"}]
    r = caller.call_strict_tool(
        messages=messages,
        tool_name="emit_fillets",
        tool_description="Emit freely selected fillet corners (vertex + two edges + radius)",
        tool_schema=to_deepseek_strict_schema(free_select_schema()),
        model_config=MODEL_CONFIG,
    )
    return list(r.arguments.get("fillets", []))


def build_wire(pts):
    wp = cq.Workplane("XY")
    for i, pt in enumerate(pts):
        if i == 0:
            wp = wp.moveTo(pt["x_mm"], pt["y_mm"])
        else:
            wp = wp.lineTo(pt["x_mm"], pt["y_mm"])
    wp = wp.close()
    return wp.wire().val()


def plot_wire(ax, w, color="#1f77b4", lw=1.8, alpha=1.0):
    for e in w.Edges():
        smp = sample_edge(e)
        ax.plot([p[0] for p in smp], [p[1] for p in smp], color=color, lw=lw, alpha=alpha)


def main():
    key = API_KEY_FILE.read_text(encoding="utf-8").strip()
    os.environ["DEEPSEEK_API_KEY"] = key

    print("=== LLM 全程真实链路：生成轮廓 → 自由选圆角 → 执行 ===\n")
    report = {}
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    for idx, (name, ver, label) in enumerate(COMBOS):
        ax = axes[idx // 3][idx % 3]
        p = make_combo(name)
        gt = generate_profile(p)

        # ── 1. LLM 生成轮廓（retry 精炼）──
        prompt = build_prompt(p, ver)
        llm_pts, res, attempts = call_llm_retry(prompt, gt, max_attempts=2)
        if res.get("match"):
            pts = llm_pts
            source = f"LLM精确(尝试{attempts}轮)"
            llm_max_err = 0.0
        else:
            pts = gt
            llm_max_err = res.get("max_dx") if res.get("max_dx") is not None else -1
            source = f"GT回退(LLM max_dx={llm_max_err}, 尝试{attempts}轮)"
        n_pts = len(pts)

        # ── 2. 候选角表 + LLM 自由选圆角 ──
        cands = build_candidate_table(pts, p.teeth_count)
        sel_prompt = build_selection_prompt(cands, p.teeth_count)
        llm_sel = call_llm_fillet(sel_prompt)
        corners, llm_out, feedback = resolve_selection(cands, llm_sel)

        # ── 3. 执行圆角 ──
        wire = build_wire(pts)
        n0 = len(list(wire.Edges()))
        fails = {}
        fw = execute_fillets(wire, corners, llm_out, p.teeth_count, pts, failures=fails)
        n1 = len(list(fw.Edges()))

        # ── 4. 绘制（每组合单独大图：左原始 右圆角）──
        plot_wire(ax, wire, color="#bbbbbb", lw=1.0, alpha=0.6)
        plot_wire(ax, fw, color="#1f77b4", lw=1.8)
        for c in corners:
            for v in (c["vertex"], c["lower_vertex"]):
                ax.plot(v[0], v[1], "o", color="#d62728", ms=3.5, zorder=5)
        ax.axhline(0, color="gray", lw=0.5, ls="--")
        ax.set_aspect("equal")
        ax.set_title(f"{label}  {p.teeth_count}齿\n{source}  选角{len(corners)}  "
                     f"边{n0}→{n1}  {fails or 'OK'}", fontsize=8)
        ax.grid(alpha=0.2)

        fig2, (axl, axr) = plt.subplots(1, 2, figsize=(12, 5))
        plot_wire(axl, wire, color="#1f77b4", lw=1.6)
        axl.axhline(0, color="gray", lw=0.5, ls="--")
        axl.set_aspect("equal")
        axl.set_title(f"{label}: 原始轮廓（{source}）", fontsize=10)
        axl.grid(alpha=0.2)
        plot_wire(axr, wire, color="#bbbbbb", lw=1.0, alpha=0.6)
        plot_wire(axr, fw, color="#1f77b4", lw=1.8)
        for c in corners:
            for v in (c["vertex"], c["lower_vertex"]):
                axr.plot(v[0], v[1], "o", color="#d62728", ms=4, zorder=5)
        axr.axhline(0, color="gray", lw=0.5, ls="--")
        axr.set_aspect("equal")
        axr.set_title(f"{label}: 圆角后（红点=LLM选中，{len(corners)}角，边{n0}→{n1}）", fontsize=10)
        axr.grid(alpha=0.2)
        fig2.suptitle(f"{label} — LLM 生成轮廓 + 自由选圆角", fontsize=11)
        fig2.tight_layout()
        fig2.savefig(OUT / f"{name}.png", dpi=140)
        plt.close(fig2)

        # ── 5. 保存（含点坐标，可重绘）──
        roles = {}
        for c in corners:
            roles.setdefault(c["role"], 0)
            roles[c["role"]] += 1
        record = {
            "teeth_count": p.teeth_count, "label": label, "source": source, "llm_max_err": llm_max_err,
            "pts": pts, "n_candidates": len(cands), "selected": roles,
            "n_bad_key": sum(1 for x in feedback if "未知顶点" in x),
            "n_bad_edge": sum(1 for x in feedback if "邻边" in x),
            "n_dup": sum(1 for x in feedback if "重复" in x),
            "feedback": feedback, "edges": (n0, n1), "failures": fails,
            "llm_sel_raw": llm_sel,
        }
        report[name] = record
        (OUT / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"[{label:8s}] 点={n_pts} {source} 选角={len(corners)} roles={roles} "
              f"边{n0}→{n1} 非法key={record['n_bad_key']} 边错={record['n_bad_edge']} 重复={record['n_dup']} "
              f"failures={fails}")

    fig.suptitle("LLM 全程真实链路 — 最终圆角后榫槽（红点=LLM自由选中的角）", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "llm_free_select_full.png", dpi=140)
    plt.close(fig)

    (OUT / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n汇总图: {OUT / 'llm_free_select_full.png'}")
    print(f"结果: {OUT / 'summary.json'}")


if __name__ == "__main__":
    main()
