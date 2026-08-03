"""多参数圆角后榫槽绘制 — 真实圆弧采样，供人工检查。

对 12 个参数组合（齿数 2~5 / 齿高 / 齿面角 / 颈部 / 连接线 / 大圆角）：
  - 左：原始轮廓（直线）
  - 右：碰撞安全圆角后（圆弧采样 24 点，显示真实圆弧）
  - 红点：被圆角的角清单顶点（上侧+下侧）
产物：output/fillet_show/{name}.png + fillet_show_all.png（汇总）
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
from fillet_corners import list_required_corners, execute_fillets

OUT = Path(__file__).resolve().parent / "output" / "fillet_show"
OUT.mkdir(parents=True, exist_ok=True)


def _norm_angle(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def sample_edge(e, n=24):
    """LINE → 两端；CIRCLE → 绕 arcCenter 采样 n 段（真实圆弧）。"""
    sp, ep = e.startPoint(), e.endPoint()
    if e.geomType() != "CIRCLE":
        return [(sp.x, sp.y), (ep.x, ep.y)]
    ac = e.arcCenter()
    r = e.radius()
    m = (sp + ep) * 0.5
    d0 = (m - ac).Length
    if d0 < 1e-9:
        return [(sp.x, sp.y), (ep.x, ep.y)]
    # 圆弧中点（弦背离圆心侧）：M = ac + (m - ac) * (r/d0)
    mx = ac.x + (m.x - ac.x) * (r / d0)
    my = ac.y + (m.y - ac.y) * (r / d0)
    a0 = math.atan2(sp.y - ac.y, sp.x - ac.x)
    aM = math.atan2(my - ac.y, mx - ac.x)
    a1 = math.atan2(ep.y - ac.y, ep.x - ac.x)
    d1 = _norm_angle(aM - a0)
    d2 = _norm_angle(a1 - aM)
    total = d1 + d2 if (d1 > 0) == (d2 > 0) else d1 - d2
    pts = []
    for k in range(n + 1):
        a = a0 + total * k / n
        pts.append((ac.x + r * math.cos(a), ac.y + r * math.sin(a)))
    return pts


def build_wire(pts):
    wp = cq.Workplane("XY")
    for i, pt in enumerate(pts):
        if i == 0:
            wp = wp.moveTo(pt["x_mm"], pt["y_mm"])
        else:
            wp = wp.lineTo(pt["x_mm"], pt["y_mm"])
    wp = wp.close()
    return wp.wire().val()


def plot_wire(ax, w, color="#1f77b4", lw=1.6, alpha=1.0):
    for e in w.Edges():
        pts = sample_edge(e)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color, lw=lw, alpha=alpha)


def neck_dec(n, outer, inner):
    return [round(outer + (inner - outer) * i / n, 2) for i in range(n + 1)]


def make(name, teeth, height, thick, top, under, neck, platform=2.0, bottom=4.0,
         bplat=2.0, flare=60, depth=26):
    return FirTreeParams(
        teeth_count=teeth, slot_depth_mm=depth,
        tooth_height_mm=height, tooth_thickness_mm=[thick] * teeth,
        top_flank_angle_deg=[top] * teeth, under_flank_angle_deg=[under] * teeth,
        neck_half_width_mm=neck, neck_platform_mm=platform,
        bottom_half_width_mm=bottom, bottom_platform_mm=bplat, bottom_flare_angle_deg=flare,
    )


COMBOS = [
    ("M1_2齿标准", make("M1", 2, [6, 5], 2, 66.7, 60, neck_dec(2, 2.6, 1.8)), {}),
    ("M2_3齿标准", make("M2", 3, [6, 5, 4], 2, 66.7, 60, neck_dec(3, 2.6, 1.8)), {}),
    ("M3_4齿", make("M3", 4, [6, 5.3, 4.7, 4], 1.5, 66.7, 60, neck_dec(4, 2.6, 1.6)), {}),
    ("M4_5齿", make("M4", 5, [5, 4.5, 4, 3.5, 3], 1.5, 66.7, 60, neck_dec(5, 2.4, 1.4)), {}),
    ("M5_大齿高", make("M5", 3, [9, 7, 5], 2, 66.7, 60, neck_dec(3, 2.6, 1.8)), {}),
    ("M6_小齿高", make("M6", 3, [3, 2.5, 2], 2, 66.7, 60, neck_dec(3, 2.6, 1.8)), {}),
    ("M7_陡齿面75°", make("M7", 3, [6, 5, 4], 2, 75, 70, neck_dec(3, 2.6, 1.8)), {}),
    ("M8_缓齿面50°", make("M8", 3, [6, 5, 4], 2, 50, 45, neck_dec(3, 2.6, 1.8)), {}),
    ("M9_齿高递增", make("M9", 3, [4, 5.5, 7], 2, 66.7, 60, neck_dec(3, 2.6, 1.8)), {}),
    ("M10_长连接线", make("M10", 3, [6, 5, 4], 2, 66.7, 60, neck_dec(3, 2.6, 1.8), platform=3.0), {}),
    ("M11_宽颈部", make("M11", 3, [6, 5, 4], 2, 66.7, 60, neck_dec(3, 3.6, 2.8), bottom=4.5), {}),
    ("M12_大圆角请求", make("M12", 3, [6, 5, 4], 2, 66.7, 60, neck_dec(3, 2.6, 1.8)), {"big": True}),
]


def role_group(key, role):
    if "tip" in key:
        return "tip"
    return role if role in ("neck", "connector") else "bottom"


def run_combo(name, p, cfg):
    pts = generate_profile(p)
    corners = list_required_corners(pts, p.teeth_count)
    if cfg.get("big"):
        rbr = {"tip": 1.5, "neck": 1.2, "connector": 1.2, "bottom": 1.5}
    else:
        rbr = {"tip": 0.8, "neck": 0.5, "connector": 0.5, "bottom": 0.6}
    llm = [{"role": c["role"], "tooth_index": c["tooth_index"], "radius_mm": rbr[role_group(c["key"], c["role"])]}
           for c in corners]
    wire = build_wire(pts)
    fails = {}
    fw = execute_fillets(wire, corners, llm, p.teeth_count, pts, failures=fails)
    return pts, corners, wire, fw, fails


def draw(ax, wire, fw, corners, title, show_corners=True):
    plot_wire(ax, wire, color="#bbbbbb", lw=1.0, alpha=0.6)  # 原始浅灰底
    plot_wire(ax, fw, color="#1f77b4", lw=1.8)
    if show_corners:
        for c in corners:
            for v in (c["vertex"], c["lower_vertex"]):
                ax.plot(v[0], v[1], "o", color="#d62728", ms=4, zorder=5)
    ax.axhline(0, color="gray", lw=0.5, ls="--")
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=9)
    ax.grid(alpha=0.2)


def main():
    results = []
    for name, p, cfg in COMBOS:
        pts, corners, wire, fw, fails = run_combo(name, p, cfg)
        n_edges0 = len(list(wire.Edges()))
        n_edges1 = len(list(fw.Edges()))
        status = "OK" if not fails else f"失败{len(fails)}角: {list(fails)}"
        summary = (f"{name}\n"
                   f"齿数={p.teeth_count} 齿高={p.tooth_height_mm} 齿厚={p.tooth_thickness_mm}\n"
                   f"Tfa={p.top_flank_angle_deg} Ufa={p.under_flank_angle_deg}\n"
                   f"颈部={p.neck_half_width_mm} 连接线={p.neck_platform_mm}\n"
                   f"角数={len(corners)} 边:{n_edges0}→{n_edges1} {status}")
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
        draw(ax1, wire, wire, [], f"{name}: 原始轮廓")
        draw(ax2, wire, fw, corners, summary)
        fig.suptitle(f"{name} — 圆角后榫槽（红点=圆角角顶点）", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"{name.replace('°', 'deg').replace('/', '_')}.png", dpi=140)
        plt.close(fig)
        results.append((name, p, cfg, pts, corners, wire, fw, fails))
        print(f"  {name:14s} {p.teeth_count}齿 角={len(corners):2d} 边:{n_edges0}→{n_edges1}(+{n_edges1-n_edges0}) {status}")

    # 汇总图 3×4
    fig, axes = plt.subplots(4, 3, figsize=(15, 16))
    for idx, (name, p, cfg, pts, corners, wire, fw, fails) in enumerate(results):
        ax = axes[idx // 3][idx % 3]
        plot_wire(ax, fw, color="#1f77b4", lw=1.4)
        for c in corners:
            for v in (c["vertex"], c["lower_vertex"]):
                ax.plot(v[0], v[1], "o", color="#d62728", ms=2.5)
        ax.axhline(0, color="gray", lw=0.5, ls="--")
        ax.set_aspect("equal")
        ax.set_title(name, fontsize=8)
        ax.grid(alpha=0.2)
    fig.suptitle("圆角后榫槽汇总（红点=圆角角顶点）", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "fillet_show_all.png", dpi=140)
    plt.close(fig)

    print(f"\n产物: {OUT}")
    print("汇总图: fillet_show_all.png")


if __name__ == "__main__":
    main()
