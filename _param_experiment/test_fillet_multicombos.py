"""多参数组合圆角测试 — 碰撞安全圆角在不同参数下的健壮性。

覆盖：齿数 2~5、齿高大/小/递增、陡/缓齿面、宽颈部、长连接线、大半径请求。
每组合验证：角清单 / 安全半径 / 圆角执行 / 全部角圆角成功。
产物：output/fillet_multicombos/
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

import cadquery as cq

from fir_tree_parametric import FirTreeParams, generate_profile
from fillet_corners import list_required_corners, compute_safe_radius, execute_fillets, verify_coverage

OUT = Path(__file__).resolve().parent / "output" / "fillet_multicombos"
OUT.mkdir(parents=True, exist_ok=True)


def make(name: str, teeth, height, thick, top, under, neck, platform=2.0, bottom=4.0,
         bplat=2.0, flare=60, depth=26) -> FirTreeParams:
    return FirTreeParams(
        teeth_count=teeth, slot_depth_mm=depth,
        tooth_height_mm=height, tooth_thickness_mm=[thick] * teeth,
        top_flank_angle_deg=[top] * teeth, under_flank_angle_deg=[under] * teeth,
        neck_half_width_mm=neck, neck_platform_mm=platform,
        bottom_half_width_mm=bottom, bottom_platform_mm=bplat, bottom_flare_angle_deg=flare,
    )


def neck_dec(n: int, outer: float, inner: float) -> list:
    return [round(outer + (inner - outer) * i / n, 2) for i in range(n + 1)]


# ── 参数组合 ────────────────────────────────────────────────────────────────

COMBOS = {
    "M1_2tooth_std": dict(fn=lambda: make("M1", 2, [6, 5], 2, 66.7, 60, neck_dec(2, 2.6, 1.8))),
    "M2_3tooth_std": dict(fn=lambda: make("M2", 3, [6, 5, 4], 2, 66.7, 60, neck_dec(3, 2.6, 1.8))),
    "M3_4tooth_std": dict(fn=lambda: make("M3", 4, [6, 5.3, 4.7, 4], 1.5, 66.7, 60, neck_dec(4, 2.6, 1.6))),
    "M4_5tooth": dict(fn=lambda: make("M4", 5, [5, 4.5, 4, 3.5, 3], 1.5, 66.7, 60, neck_dec(5, 2.4, 1.4))),
    "M5_large_teeth": dict(fn=lambda: make("M5", 3, [9, 7, 5], 2, 66.7, 60, neck_dec(3, 2.6, 1.8))),
    "M6_small_teeth": dict(fn=lambda: make("M6", 3, [3, 2.5, 2], 2, 66.7, 60, neck_dec(3, 2.6, 1.8))),
    "M7_steep_flank": dict(fn=lambda: make("M7", 3, [6, 5, 4], 2, 75, 70, neck_dec(3, 2.6, 1.8))),
    "M8_gentle_flank": dict(fn=lambda: make("M8", 3, [6, 5, 4], 2, 50, 45, neck_dec(3, 2.6, 1.8))),
    "M9_increasing": dict(fn=lambda: make("M9", 3, [4, 5.5, 7], 2, 66.7, 60, neck_dec(3, 2.6, 1.8))),
    "M10_long_conn": dict(fn=lambda: make("M10", 3, [6, 5, 4], 2, 66.7, 60, neck_dec(3, 2.6, 1.8), platform=3.0)),
    "M11_wide_neck": dict(fn=lambda: make("M11", 3, [6, 5, 4], 2, 66.7, 60, neck_dec(3, 3.6, 2.8), bottom=4.5)),
    "M12_big_radius": dict(fn=lambda: make("M12", 3, [6, 5, 4], 2, 66.7, 60, neck_dec(3, 2.6, 1.8)), big_radius=True),
}

# 请求半径（角色 → 半径）
def req_radius(name: str) -> dict:
    if COMBOS[name].get("big_radius"):
        return {"tip": 1.5, "neck": 1.2, "connector": 1.2, "bottom": 1.5}  # 过大 → 应 clamp
    return {"tip": 0.8, "neck": 0.5, "connector": 0.5, "bottom": 0.6}


def build_wire(pts):
    wp = cq.Workplane("XY")
    for i, pt in enumerate(pts):
        if i == 0:
            wp = wp.moveTo(pt["x_mm"], pt["y_mm"])
        else:
            wp = wp.lineTo(pt["x_mm"], pt["y_mm"])
    wp = wp.close()
    return wp.wire().val()


def polygon(w):
    xs, ys = [], []
    for e in list(w.Edges()):
        vs = list(e.Vertices())
        xs.append(vs[0].X)
        ys.append(vs[0].Y)
    xs.append(xs[0])
    ys.append(ys[0])
    return xs, ys


def main():
    print("=== 多参数组合圆角测试 (%d 组合) ===\n" % len(COMBOS))
    summary = {}
    all_ok = True

    for name, cfg in COMBOS.items():
        p = cfg["fn"]()
        pts = generate_profile(p)
        corners = list_required_corners(pts, p.teeth_count)
        n_upper = 5 + 4 * p.teeth_count

        # 请求半径（含 LLM 全覆盖）
        rbr = req_radius(name)
        llm = []
        for c in corners:
            g = "tip" if "tip" in c["key"] else (c["role"] if c["role"] in ("neck", "connector") else "bottom")
            llm.append({"role": c["role"], "tooth_index": c["tooth_index"], "radius_mm": rbr[g]})

        # 覆盖验证
        ok_cov, missing, extra, dup = verify_coverage(corners, llm)
        # 安全半径
        safe = compute_safe_radius(corners, pts, rbr)
        max_r = max(safe.values())
        min_r = min(safe.values())
        # 相邻碰撞检查
        collide = False
        idx_sorted = sorted(corners, key=lambda c: c["vertex_idx"])
        n = len(pts)
        for k in range(len(idx_sorted) - 1):
            a, b = idx_sorted[k], idx_sorted[k + 1]
            if b["vertex_idx"] - a["vertex_idx"] == 1:
                L = ((pts[a["vertex_idx"]]["x_mm"] - pts[b["vertex_idx"]]["x_mm"]) ** 2
                     + (pts[a["vertex_idx"]]["y_mm"] - pts[b["vertex_idx"]]["y_mm"]) ** 2) ** 0.5
                if safe[a["key"]] + safe[b["key"]] > L + 0.01:
                    collide = True

        # 执行圆角
        wire = build_wire(pts)
        n_edges0 = len(list(wire.Edges()))
        fw = execute_fillets(wire, corners, llm, p.teeth_count, pts)
        n_edges1 = len(list(fw.Edges()))
        inc = n_edges1 - n_edges0
        n_corners = len(corners)
        # 全部圆角成功 = 边数增加 ≈ 角数（每角 +1 弧边，替换尖角）
        all_filleted = inc >= n_corners

        status = "PASS" if (ok_cov and not collide and all_filleted and n_edges1 > n_edges0) else "FAIL"
        if status == "FAIL":
            all_ok = False
        summary[name] = {"n_corners": n_corners, "safe_range": (round(min_r, 2), round(max_r, 2)),
                         "edges": (n_edges0, n_edges1), "inc": inc, "collide": collide,
                         "all_filleted": all_filleted, "status": status}

        # 图（原始 vs 圆角）
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        for ax, (w_, title) in enumerate([(wire, "原始"), (fw, "碰撞安全圆角")]):
            xs, ys = polygon(w_)
            axes[ax].plot(xs, ys, "-o", ms=2.5, lw=1.2)
            axes[ax].axhline(0, color="gray", lw=0.5, ls="--")
            axes[ax].set_aspect("equal")
            axes[ax].set_title(f"{name}: {title}", fontsize=9)
            axes[ax].grid(alpha=0.2)
        fig.suptitle(f"{name}: {p.teeth_count}齿 {p.tooth_height_mm} {status}", fontsize=10)
        fig.tight_layout()
        fig.savefig(OUT / f"{name}.png", dpi=140)
        plt.close(fig)

        print("%-16s %2d齿 角=%2d 安全r=[%.2f,%.2f] 边:%d→%d(+%d) 碰撞=%s 全圆角=%s -> %s" % (
            name, p.teeth_count, n_corners, min_r, max_r, n_edges0, n_edges1, inc,
            collide, all_filleted, status))

    print("\n总结:", "全部组合通过" if all_ok else "有组合失败")
    print("产物:", OUT)


if __name__ == "__main__":
    main()
