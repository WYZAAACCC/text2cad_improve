"""圆角代码深度分析 — 验证可疑逻辑点。

目标：
  1. 每个必须圆角的角：内角(凸/凹)、邻边长度、请求半径 vs 安全半径（clamp 程度）
  2. 相邻角对共享边长度 vs 两角半径和（碰撞边界验证）
  3. 验证 compute_safe_radius 下侧碰撞检查是否"死代码"（ib-ia!=1 恒跳过）
  4. 圆角后实际圆弧半径（真圆弧？）
  5. 位置匹配：圆角后顶点数量变化、切点离目标尖角的距离
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import math
import cadquery as cq

from fir_tree_parametric import FirTreeParams, generate_profile
from fillet_corners import list_required_corners, compute_safe_radius, execute_fillets
from fillet_strategy import annotate_roles


def neck_dec(n: int, outer: float, inner: float) -> list:
    return [round(outer + (inner - outer) * i / n, 2) for i in range(n + 1)]


def make_3tooth():
    return FirTreeParams(
        teeth_count=3, slot_depth_mm=26,
        tooth_height_mm=[6, 5, 4], tooth_thickness_mm=[2, 2, 2],
        top_flank_angle_deg=[66.7, 66.7, 66.7], under_flank_angle_deg=[60, 60, 60],
        neck_half_width_mm=neck_dec(3, 2.6, 1.8), neck_platform_mm=2.0,
        bottom_half_width_mm=4.0, bottom_platform_mm=2.0, bottom_flare_angle_deg=60,
    )


def interior_angle(pa, pb, pc):
    """顶点 pb 处的内角（度）。u=pa->pb, v=pb->pc，用叉积/点积取 |夹角|。"""
    ux, uy = pa[0] - pb[0], pa[1] - pb[1]
    vx, vy = pc[0] - pb[0], pc[1] - pb[1]
    dot = ux * vx + uy * vy
    cross = ux * vy - uy * vx
    a = math.atan2(abs(cross), dot)
    return math.degrees(a)


def turn_dir(pa, pb, pc):
    """有向转向：正=左转，负=右转。用叉积符号。"""
    ux, uy = pa[0] - pb[0], pa[1] - pb[1]
    vx, vy = pc[0] - pb[0], pc[1] - pb[1]
    return 1 if (ux * vy - uy * vx) > 0 else -1


def build_wire(pts):
    wp = cq.Workplane("XY")
    for i, pt in enumerate(pts):
        if i == 0:
            wp = wp.moveTo(pt["x_mm"], pt["y_mm"])
        else:
            wp = wp.lineTo(pt["x_mm"], pt["y_mm"])
    wp = wp.close()
    return wp.wire().val()


def main():
    p = make_3tooth()
    pts = generate_profile(p)
    n_upper = 5 + 4 * p.teeth_count
    total = len(pts)
    corners = list_required_corners(pts, p.teeth_count)
    upper_roles = annotate_roles(p.teeth_count)

    print(f"=== 3齿标准参数 点结构 ===  total={total} 上侧={n_upper}")
    print("上侧点序列（索引 | 角色 | 坐标）：")
    for i in range(n_upper):
        pt = pts[i]
        mark = ""
        for c in corners:
            if c["vertex_idx"] == i:
                mark = f"  <<< {c['key']}"
        print(f"  [{i:2d}] {upper_roles[i]:16s} ({pt['x_mm']:7.3f}, {pt['y_mm']:7.3f}){mark}")

    print(f"\n=== 角清单（{len(corners)} 个）内角分析 ===")
    print(f"{'key':26s} {'idx':>3s} {'内角':>6s} {'凸凹':>3s} {'邻边a':>6s} {'邻边b':>6s} {'顶点':>18s}")
    for c in corners:
        i = c["vertex_idx"]
        pa = pts[(i - 1) % n_upper]
        pb = pts[i]
        pc = pts[(i + 1) % n_upper]
        ang = interior_angle((pa["x_mm"], pa["y_mm"]), (pb["x_mm"], pb["y_mm"]), (pc["x_mm"], pc["y_mm"]))
        td = turn_dir((pa["x_mm"], pa["y_mm"]), (pb["x_mm"], pb["y_mm"]), (pc["x_mm"], pc["y_mm"]))
        # 凹角 = 轮廓方向上的反射角。简化：内角>150° 且转向与轮廓主导相反
        # 实际用邻边方向判断：齿根处尖角通常 <120°
        la = math.dist(c["edge_a"][0], c["edge_a"][1])
        lb = math.dist(c["edge_b"][0], c["edge_b"][1])
        convex = "凹" if ang > 160 else ("凸" if ang < 140 else "平")
        print(f"{c['key']:26s} {i:3d} {ang:6.1f} {convex:>3s} {la:6.2f} {lb:6.2f} ({pb['x_mm']:7.3f},{pb['y_mm']:7.3f})")

    # ── 碰撞边界检查（相邻角对）──
    rbr = {"tip": 0.8, "neck": 0.5, "connector": 0.5, "bottom": 0.6}
    safe = compute_safe_radius(corners, pts, rbr)
    print(f"\n=== 安全半径 vs 请求半径 ===")
    for c in corners:
        g = "tip" if "tip" in c["key"] else (c["role"] if c["role"] in ("neck", "connector") else "bottom")
        req = rbr[g]
        print(f"  {c['key']:26s} 请求={req:.2f}  安全={safe[c['key']]:.2f}  {'CLAMP' if safe[c['key']] < req - 1e-9 else ''}")

    # 相邻角对（上侧顶点索引差1）
    idx_sorted = sorted(corners, key=lambda c: c["vertex_idx"])
    print(f"\n=== 相邻角对碰撞边界（上侧）===")
    for k in range(len(idx_sorted) - 1):
        a, b = idx_sorted[k], idx_sorted[k + 1]
        if b["vertex_idx"] - a["vertex_idx"] != 1:
            continue
        pa = pts[a["vertex_idx"]]
        pb = pts[b["vertex_idx"]]
        L = math.dist((pa["x_mm"], pa["y_mm"]), (pb["x_mm"], pb["y_mm"]))
        s = safe[a["key"]] + safe[b["key"]]
        print(f"  {a['key']:18s} + {b['key']:18s} 共享边={L:.3f}  半径和={s:.3f}  {'OK' if s <= L else '超标!!'}")

    # ── 验证下侧碰撞检查是否生效（修复 A 后：按 lower_vertex_idx 升序）──
    print(f"\n=== compute_safe_radius 下侧碰撞检查验证（修A后）===")
    order_lower = sorted(corners, key=lambda c: c["lower_vertex_idx"])
    hits = 0
    for k in range(len(order_lower) - 1):
        a, b = order_lower[k], order_lower[k + 1]
        if b["lower_vertex_idx"] - a["lower_vertex_idx"] == 1:
            hits += 1
    total_pairs = len(order_lower) - 1
    print(f"  下侧相邻角对={total_pairs}  按 lower_vertex_idx 升序命中={hits}  {'PASS' if hits == total_pairs else 'FAIL'}")

    # ── 实际执行圆角，检查圆弧半径 ──
    print(f"\n=== 圆角执行与圆弧检查 ===")
    llm = []
    for c in corners:
        g = "tip" if "tip" in c["key"] else (c["role"] if c["role"] in ("neck", "connector") else "bottom")
        llm.append({"role": c["role"], "tooth_index": c["tooth_index"], "radius_mm": rbr[g]})
    wire = build_wire(pts)
    n0 = len(list(wire.Edges()))
    fw = execute_fillets(wire, corners, llm, p.teeth_count, pts)
    n1 = len(list(fw.Edges()))
    print(f"  边数: {n0} -> {n1} (+{n1 - n0}), 角数={len(corners)}")
    # 统计圆弧
    from cadquery import Edge
    arcs, lines, other = 0, 0, 0
    arc_radii = []
    for e in list(fw.Edges()):
        g = e.geomType()
        if g == "LINE":
            lines += 1
        elif g == "CIRCLE":
            arcs += 1
            arc_radii.append(round(e.radius(), 3))
        else:
            other += 1
    print(f"  直线={lines} 圆弧={arcs} 其他={other}")
    if arc_radii:
        print(f"  圆弧半径分布: {sorted(set(arc_radii))}")

    # ── 位置匹配：原始尖角是否都被替换、切点间是否碰撞 ──
    print(f"\n=== 圆角后尖角消失 & 相邻切点距离 ===")
    # 原始尖角顶点
    orig_verts = [(pts[i]["x_mm"], pts[i]["y_mm"]) for i in range(total)]
    new_verts = [(v.X, v.Y) for v in list(fw.Vertices())]
    # 被圆角的角顶点应该不再出现（或接近圆弧端点）
    missing = 0
    for c in corners:
        for target in (c["vertex"], c["lower_vertex"]):
            # 找新 wire 中离它最近的顶点
            d = min(math.dist(target, nv) for nv in new_verts)
            if d > 0.15:  # 原尖角被圆角后应无顶点残留
                missing += 1
    print(f"  角顶点数={len(corners) * 2}  圆角后被圆弧替换(无残顶点)数={len(corners) * 2 - missing} 未替换={missing}")


if __name__ == "__main__":
    main()
