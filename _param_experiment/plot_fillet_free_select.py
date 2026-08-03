"""LLM 自由选择圆角 — 演示图（程序模拟 LLM 选角，可复现）。

3 齿标准参数，三张对比：
  原始轮廓 | LLM 只选齿根圆角 | LLM 全选圆角
红点 = LLM 选中的角（顶点）。真实圆弧采样显示。
产物：output/fillet_free_select/
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

import cadquery as cq

from fir_tree_parametric import FirTreeParams, generate_profile
from fillet_free_select import build_candidate_table, resolve_selection, ROLE_MEANING
from fillet_corners import execute_fillets
from plot_fillet_show import sample_edge  # 复用圆弧采样

OUT = Path(__file__).resolve().parent / "output" / "fillet_free_select"
OUT.mkdir(parents=True, exist_ok=True)


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


def make_3tooth():
    return FirTreeParams(
        teeth_count=3, slot_depth_mm=26,
        tooth_height_mm=[6, 5, 4], tooth_thickness_mm=[2, 2, 2],
        top_flank_angle_deg=[66.7] * 3, under_flank_angle_deg=[60] * 3,
        neck_half_width_mm=[2.6, 2.33, 2.07, 1.8], neck_platform_mm=2.0,
        bottom_half_width_mm=4.0, bottom_platform_mm=2.0, bottom_flare_angle_deg=60,
    )


def llm_select(cands, roles_include):
    """程序模拟 LLM：只选指定角色的角，半径按角色参考值。"""
    ref = {"tip_flank_top": 0.8, "tip_platform_end": 0.8, "neck": 0.5,
           "connector": 0.5, "bottom_flare": 0.6, "bottom_platform": 0.6, "root": 0.6,
           "mouth": 0.5}
    out = []
    for c in cands:
        if c["role"] in roles_include:
            out.append({"vertex": c["key"], "edge_a": c["edge_a_key"], "edge_b": c["edge_b_key"],
                        "radius_mm": ref[c["role"]]})
    return out


def draw(ax, wire, fw, corners, title):
    plot_wire(ax, wire, color="#bbbbbb", lw=1.0, alpha=0.6)
    plot_wire(ax, fw, color="#1f77b4", lw=1.8)
    for c in corners:
        for v in (c["vertex"], c["lower_vertex"]):
            ax.plot(v[0], v[1], "o", color="#d62728", ms=4, zorder=5)
    ax.axhline(0, color="gray", lw=0.5, ls="--")
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=9)
    ax.grid(alpha=0.2)


def main():
    p = make_3tooth()
    pts = generate_profile(p)
    cands = build_candidate_table(pts, p.teeth_count)
    wire = build_wire(pts)

    # LLM 自由选择场景
    scenes = [
        ("root_only", {"neck", "connector"}, "LLM 只选齿根（neck+connector）"),
        ("full", {"neck", "connector", "tip_flank_top", "tip_platform_end",
                  "bottom_flare", "bottom_platform", "root"}, "LLM 全选（齿根+齿顶+槽底）"),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    draw(axes[0], wire, wire, [], "原始轮廓（无圆角）")
    summary = {}
    for idx, (tag, roles, title) in enumerate(scenes, start=1):
        llm = llm_select(cands, roles)
        corners, llm_out, feedback = resolve_selection(cands, llm)
        fails = {}
        fw = execute_fillets(wire, corners, llm_out, p.teeth_count, pts, failures=fails)
        n0, n1 = len(list(wire.Edges())), len(list(fw.Edges()))
        draw(axes[idx], wire, fw, corners, f"{title}\n选中 {len(corners)} 角  边 {n0}→{n1}  {fails or 'OK'}")
        summary[tag] = {"n_corners": len(corners), "roles": [c["role"] for c in corners],
                        "feedback": feedback, "edges": (n0, n1)}
    fig.suptitle("LLM 自由选择圆角 — 演示（红点=LLM选中的角）", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "free_select_demo.png", dpi=140)
    plt.close(fig)

    # 候选角表保存（供 prompt 参考）
    import json
    cand_info = [{"key": c["key"], "role": c["role"], "meaning": ROLE_MEANING[c["role"]],
                  "vertex": c["vertex"], "edge_a": c["edge_a_key"], "edge_b": c["edge_b_key"]}
                 for c in cands]
    (OUT / "candidate_table.json").write_text(
        json.dumps(cand_info, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "scene_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"演示图: {OUT / 'free_select_demo.png'}")
    for tag, s in summary.items():
        print(f"  {tag}: 选中{len(s['roles'])}角 roles={s['roles']} 边{s['edges']} feedback={s['feedback']}")


if __name__ == "__main__":
    main()
