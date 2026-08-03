"""参数化能力全面测试 — 验证生成器对多种参数组合的健壮性。

覆盖：齿数 1~5、齿高/递减/递增/大/小、齿面角陡缓、颈部宽窄、槽底变化等。
验证每组合：生成成功 / 轴对称 / 齿根斜线共线 / 深度合理。
产物：output/parametric_capability/
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

from fir_tree_parametric import FirTreeParams, generate_profile

OUT = Path(__file__).resolve().parent / "output" / "parametric_capability"
OUT.mkdir(parents=True, exist_ok=True)


def neck_linear(n: int, outer: float, inner: float) -> list:
    """生成线性递减颈部半宽数组（长度 n+1，含最后颈部）。"""
    return [round(outer + (inner - outer) * i / n, 2) for i in range(n + 1)]


def heights(n: int, outer: float, inner: float) -> list:
    """齿高数组（外→内）。outer=槽口齿高，inner=圆心侧齿高。"""
    if n == 1:
        return [outer]
    return [round(outer + (inner - outer) * i / (n - 1), 2) for i in range(n)]


# ── 测试组合定义 ───────────────────────────────────────────────────────────

COMBOS = {
    # 1 齿（最简）
    "T01_1tooth": dict(teeth_count=1, tooth_height=[7], tooth_thickness=[2],
                       top_flank=[66.7], under_flank=[60], neck=neck_linear(1, 2.6, 2.0),
                       bottom=4.0, bottom_platform=2.0, flare=60),
    # 2 齿等高
    "T02_2tooth_equal": dict(teeth_count=2, tooth_height=[5, 5], tooth_thickness=[2, 2],
                             top_flank=[66.7, 66.7], under_flank=[60, 60], neck=neck_linear(2, 2.6, 2.2),
                             bottom=4.0, bottom_platform=2.0, flare=60),
    # 3 齿标准（S1_dec）
    "T03_3tooth_standard": dict(teeth_count=3, tooth_height=[7, 5.5, 4], tooth_thickness=[2, 2, 2],
                                top_flank=[66.7, 66.7, 66.7], under_flank=[60, 60, 60],
                                neck=neck_linear(3, 2.6, 1.8), bottom=4.0, bottom_platform=2.0, flare=60),
    # 4 齿
    "T04_4tooth": dict(teeth_count=4, tooth_height=[8, 6.5, 5, 3.5], tooth_thickness=[1.5, 1.5, 1.5, 1.5],
                       top_flank=[66.7] * 4, under_flank=[60] * 4, neck=neck_linear(4, 2.6, 1.6),
                       bottom=4.0, bottom_platform=2.0, flare=60),
    # 5 齿（极限）
    "T05_5tooth": dict(teeth_count=5, tooth_height=[6, 5, 4, 3, 2], tooth_thickness=[1, 1, 1, 1, 1],
                       top_flank=[66.7] * 5, under_flank=[60] * 5, neck=neck_linear(5, 2.4, 1.4),
                       bottom=3.5, bottom_platform=1.5, flare=60),
    # 陡齿面角
    "T06_steep_flank": dict(teeth_count=3, tooth_height=[6, 5, 4], tooth_thickness=[2, 2, 2],
                            top_flank=[75, 75, 75], under_flank=[70, 70, 70], neck=neck_linear(3, 2.6, 1.8),
                            bottom=4.0, bottom_platform=2.0, flare=60),
    # 缓齿面角
    "T07_gentle_flank": dict(teeth_count=3, tooth_height=[6, 5, 4], tooth_thickness=[2, 2, 2],
                             top_flank=[50, 50, 50], under_flank=[45, 45, 45], neck=neck_linear(3, 2.6, 1.8),
                             bottom=4.0, bottom_platform=2.0, flare=60),
    # 大齿高
    "T08_large_teeth": dict(teeth_count=3, tooth_height=[10, 8, 6], tooth_thickness=[2, 2, 2],
                            top_flank=[66.7] * 3, under_flank=[60] * 3, neck=neck_linear(3, 2.6, 1.8),
                            bottom=4.0, bottom_platform=2.0, flare=60),
    # 小齿高
    "T09_small_teeth": dict(teeth_count=3, tooth_height=[3, 2.5, 2], tooth_thickness=[2, 2, 2],
                            top_flank=[66.7] * 3, under_flank=[60] * 3, neck=neck_linear(3, 2.6, 1.8),
                            bottom=4.0, bottom_platform=2.0, flare=60),
    # 宽颈部
    "T10_wide_neck": dict(teeth_count=3, tooth_height=[7, 5.5, 4], tooth_thickness=[2, 2, 2],
                          top_flank=[66.7] * 3, under_flank=[60] * 3, neck=neck_linear(3, 4.0, 3.0),
                          bottom=4.5, bottom_platform=2.0, flare=60),
    # 窄槽底 + 小外扩角
    "T11_narrow_bottom": dict(teeth_count=3, tooth_height=[7, 5.5, 4], tooth_thickness=[2, 2, 2],
                              top_flank=[66.7] * 3, under_flank=[60] * 3, neck=neck_linear(3, 2.6, 1.8),
                              bottom=3.0, bottom_platform=1.0, flare=45),
    # 长连接线
    "T12_long_connector": dict(teeth_count=3, tooth_height=[7, 5.5, 4], tooth_thickness=[2, 2, 2],
                               top_flank=[66.7] * 3, under_flank=[60] * 3, neck=neck_linear(3, 2.6, 1.8),
                               bottom=4.0, bottom_platform=2.0, flare=60, conn=3.0),
    # 齿高递增（圆心侧更高）
    "T13_increasing": dict(teeth_count=3, tooth_height=[4, 5.5, 7], tooth_thickness=[2, 2, 2],
                           top_flank=[66.7] * 3, under_flank=[60] * 3, neck=neck_linear(3, 2.6, 1.8),
                           bottom=4.0, bottom_platform=2.0, flare=60),
}


def build(cfg: dict) -> FirTreeParams:
    return FirTreeParams(
        teeth_count=cfg["teeth_count"],
        slot_depth_mm=cfg.get("depth", 20 + cfg["teeth_count"] * 10),
        tooth_height_mm=cfg["tooth_height"],
        tooth_thickness_mm=cfg["tooth_thickness"],
        top_flank_angle_deg=cfg["top_flank"],
        under_flank_angle_deg=cfg["under_flank"],
        neck_half_width_mm=cfg["neck"],
        neck_platform_mm=cfg.get("conn", 2.0),
        bottom_half_width_mm=cfg["bottom"],
        bottom_platform_mm=cfg["bottom_platform"],
        bottom_flare_angle_deg=cfg["flare"],
    )


def verify(p: FirTreeParams, pts: list) -> list:
    """验证：对称性 + 齿根斜线共线 + 深度合理。返回问题列表。"""
    issues = []
    N = len(pts)
    half = N // 2
    # 对称性
    for i in range(half):
        a, b = pts[i], pts[N - 1 - i]
        if abs(a["x_mm"] - b["x_mm"]) > 1e-6 or abs(a["y_mm"] + b["y_mm"]) > 1e-6:
            issues.append(f"不对称: [{i}] vs [{N-1-i}]")
            break
    # 齿根斜线：上侧 y<3 且 x<-2 的点（颈部+连接线），去掉口部楔形点(x最大)和根部(x最小)后应共线
    neck_pts = [pt for pt in pts[:half] if pt["y_mm"] < 3.0 and pt["x_mm"] < -2]
    if len(neck_pts) >= 5:
        core = neck_pts[1:-1]  # 排除最外(口部楔形)和最内(根部)
        slopes = []
        for j in range(len(core) - 1):
            dx = core[j + 1]["x_mm"] - core[j]["x_mm"]
            dy = core[j + 1]["y_mm"] - core[j]["y_mm"]
            if abs(dx) > 1e-6:
                slopes.append(dy / dx)
        if slopes and (max(slopes) - min(slopes)) > 0.01:
            issues.append(f"齿根斜线不共线: 斜率 {min(slopes):.4f}~{max(slopes):.4f}")
    # 深度为正
    depth = -min(pt["x_mm"] for pt in pts)
    if depth <= 0:
        issues.append("深度异常")
    return issues


def main():
    print("=== 参数化能力测试 (%d 组合) ===\n" % len(COMBOS))
    results = {}
    fig, axes = plt.subplots(len(COMBOS), 1, figsize=(10, 4 * len(COMBOS)))
    if len(COMBOS) == 1:
        axes = [axes]
    for (name, cfg), ax in zip(COMBOS.items(), axes):
        p = build(cfg)
        pts = generate_profile(p)
        issues = verify(p, pts)
        results[name] = {"ok": not issues, "issues": issues, "n_points": len(pts), "depth": round(-min(pt['x_mm'] for pt in pts), 1)}
        xs = [pt["x_mm"] for pt in pts] + [pts[0]["x_mm"]]
        ys = [pt["y_mm"] for pt in pts] + [pts[0]["y_mm"]]
        ax.plot(xs, ys, "-o", ms=2, lw=1, color="#1f77b4")
        ax.axhline(0, color="gray", lw=0.5, ls="--")
        ax.set_aspect("equal")
        status = "OK" if not issues else "FAIL"
        extra = ("  " + "; ".join(issues[:2])) if issues else ""
        ax.set_title(f"{name}: teeth={p.teeth_count} h={cfg['tooth_height']} {status}{extra}", fontsize=9)
        ax.grid(alpha=0.2)
        # 每个组合单独保存一张图
        fig2, ax2 = plt.subplots(figsize=(8, 6))
        ax2.plot(xs, ys, "-o", ms=4, lw=1.5, color="#1f77b4")
        ax2.axhline(0, color="gray", lw=0.6, ls="--")
        ax2.set_aspect("equal")
        ax2.set_title(f"{name}: teeth={p.teeth_count} h={cfg['tooth_height']} 顶角={cfg['top_flank']} 颈={cfg['neck']}", fontsize=9)
        ax2.set_xlabel("radial x"); ax2.set_ylabel("half-width y")
        ax2.grid(alpha=0.3)
        fig2.tight_layout()
        fig2.savefig(OUT / f"{name}.png", dpi=150)
        plt.close(fig2)
    fig.tight_layout()
    fig.savefig(OUT / "all_combos.png", dpi=120)
    plt.close(fig)

    # 汇总表
    print("%-22s %-6s %-8s %-8s %s" % ("组合", "点数", "深度", "状态", "问题"))
    all_ok = True
    for name, r in results.items():
        print("%-22s %-6d %-8.1f %-8s %s" % (name, r["n_points"], r["depth"], "OK" if r["ok"] else "FAIL", "; ".join(r["issues"])))
        if not r["ok"]:
            all_ok = False
    print("\n总结:", "全部组合通过" if all_ok else "有组合失败，见上")
    print("产物:", OUT)


if __name__ == "__main__":
    main()
