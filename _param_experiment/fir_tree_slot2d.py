"""枞树形榫槽二维参数化生成器 — 严格参照 fir_tree_parametric.py（HB5965 格式与要求）。

方法（文档 §20-21）：尖角骨架 → CreateFillet（圆角相切）→ Trim → Mirror（X=0）→ Close。

结构与要求（参照 fir_tree_parametric.py 的 generate_profile）：
  - 每齿 4 段：升面（齿根→齿顶，beta 角）+ 齿顶平台（径向跨度 tooth_thickness）
             + 降面（alpha 角）+ 连接线（径向跨度 neck_platform）。
  - **连接线共线**：所有齿根/降面终点/连接线端点落在同一条颈部斜线上
    （颈部斜线穿过第一个齿根与最后一个降面终点；X_neck(Y) 线性插值）。
  - 圆角后连接线两端圆弧与连接线相切（圆角切点落在连接线段上）。
  - 参数：neck_half[]（齿根半宽 len=N+1，口→底递减 = 从内到外逐渐扩大）、
    tooth_height[]（齿顶凸出）、tooth_thickness[]（平台径向跨度）、
    beta[]（升面角，与 +X 夹角）、alpha[]（降面角，>90° 收拢）、
    Rc[]/Rt[]/Rr[]（齿顶/齿根平台/齿根凹口）、neck_platform（连接线径向跨度）。

坐标系（文档 §1/§10）：X 周向（右半边 X>0），Y 径向（向深处 -Y），X=0 对称中心线。
角度以 +X 为 0°。非承载面角 beta（x 增）、承载面角 alpha（x 减，>90°）。
"""
from __future__ import annotations

import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ── 基本几何函数 ───────────────────────────────────────────────

def _vec(a, b):
    return (b[0] - a[0], b[1] - a[1])


def _norm(v):
    return math.hypot(v[0], v[1])


def _fillet_geom(P0, P1, P2, R):
    """尖角 P0→P1→P2 处半径 R 圆角的几何。返回 (T1, T2, s1, s2, C, a1, da, R) 或 None。

    T1 在 LineA(P0→P1) 的 P0 侧（s1∈[-lA,0]，span=-s1）；T2 在 LineB(P1→P2) 的 P2 侧
    （s2∈[0,lB]，span=s2）。C 为圆心，da 为有向弧角（短弧）。切点超界返回 None。
    """
    vA = _vec(P0, P1)
    vB = _vec(P1, P2)
    lA, lB = _norm(vA), _norm(vB)
    if lA < 1e-9 or lB < 1e-9:
        return None
    uA = (vA[0] / lA, vA[1] / lA)
    uB = (vB[0] / lB, vB[1] / lB)
    cross = uA[0] * uB[1] - uA[1] * uB[0]
    if cross >= 0:
        nA, nB = (-uA[1], uA[0]), (-uB[1], uB[0])
    else:
        nA, nB = (uA[1], -uA[0]), (uB[1], -uB[0])
    vx, vy = nA[0] + nB[0], nA[1] + nB[1]
    vl = math.hypot(vx, vy)
    if vl < 1e-9:
        return None
    vx, vy = vx / vl, vy / vl
    cos_a2 = max(min(nA[0] * vx + nA[1] * vy, 1.0), -1.0)
    d = R / max(cos_a2, 1e-6)
    C = (P1[0] + vx * d, P1[1] + vy * d)
    s1 = (C[0] - P1[0]) * uA[0] + (C[1] - P1[1]) * uA[1]
    s2 = (C[0] - P1[0]) * uB[0] + (C[1] - P1[1]) * uB[1]
    if s1 < -lA - 1e-6 or s1 > 1e-6 or s2 < -1e-6 or s2 > lB + 1e-6:
        return None
    T1 = (P1[0] + s1 * uA[0], P1[1] + s1 * uA[1])
    T2 = (P1[0] + s2 * uB[0], P1[1] + s2 * uB[1])
    a1 = math.atan2(T1[1] - C[1], T1[0] - C[0])
    a2 = math.atan2(T2[1] - C[1], T2[0] - C[0])
    da = (a2 - a1) % (2 * math.pi)
    if da > math.pi:
        da -= 2 * math.pi
    return (T1, T2, s1, s2, C, a1, da, R)


def _arc_points(geom, npts=None):
    """圆角几何 → [T1, 圆弧点..., T2]。圆弧点间距自适应（~0.25mm，2~9 点）。"""
    T1, T2, s1, s2, C, a1, da, R = geom
    if npts is None:
        npts = max(2, min(9, int(round(R * abs(da) / 0.25)) + 1))
    pts = [T1]
    for k in range(1, npts - 1):          # k=npts-1 时 a=a2 与 T2 重合，排除避免重复点
        a = a1 + da * k / (npts - 1.0)
        pts.append((C[0] + R * math.cos(a), C[1] + R * math.sin(a)))
    pts.append(T2)
    return pts


# ── 参数结构（HB5965 每齿独立参数）──

def make_params(N=3, **over):
    base = {
        "N": N,
        "slot_depth": 26.0,                     # 槽总深（元数据）
        "W_open": 10.0, "H_neck": 3.0, "R_neck": 1.0,
        "neck_half": [4.5, 3.4, 2.3, 1.2],      # 齿根半宽 len=N+1：口→底递减（口底差 3.3）
                                                #   → 连接线/颈部斜线斜率 dX/dY≈0.29（≈0.3）
        "tooth_height": [1.8, 1.6, 1.4],        # 齿顶凸出（半宽）
        "tooth_thickness": [0.8, 0.8, 0.8],     # 齿顶平台径向跨度
        "neck_platform": 0.8,                   # 连接线径向跨度
        "beta": [45.0, 45.0, 45.0],             # 非承力边（升面）角：45° → 陡（斜率 tan45≈1.00）
        "alpha": [165.0, 165.0, 165.0],         # 承力边（降面）角：180-α=15° → 缓（斜率 tan15≈0.27）
        "Rc": [0.6, 0.5, 0.4],                  # 齿顶圆角
        "Rt": [0.4, 0.4, 0.35],                 # 齿根平台圆角
        "Rr": [0.5, 0.5, 0.5],                  # 齿根凹口（连接线两端）圆角
        # 卡榫状槽底：连接线终点 → 外扩 → 平台 → 根部收窄 → 中心平底
        "bottom_half_width": 2.2,               # 底部平台半宽（外扩目标，缩小）
        "bottom_flare_angle": 60.0,             # 外扩角（与径向夹角）
        "bottom_platform": 1.2,                 # 平台径向跨度（缩小）
        "bottom_tip_half": 1.2,                 # 根部收窄后半宽（中心平底，缩小）
        "bottom_tip_depth": 0.8,                # 收窄段径向深度（缩小）
        "R_shoulder": 0.4,                      # 连接线终点→外扩壁
        "R_flare": 0.4,                         # 外扩壁→平台
        "R_plat": 0.4,                          # 平台→收窄壁
        "R_tip": 0.3,                           # 收窄壁→中心平底
    }
    base.update(over)
    return base


def _validate(P):
    N = P["N"]
    assert len(P["neck_half"]) == N + 1, f"neck_half 长度须=N+1"
    for key in ("tooth_height", "tooth_thickness", "beta", "alpha", "Rc", "Rt", "Rr"):
        assert len(P[key]) == N, f"{key} 长度须=N"
    for i in range(N):
        assert 0.0 < P["beta"][i] < 90.0, f"beta[{i}] 须在 (0,90)"
        assert 90.0 < P["alpha"][i] < 180.0, f"alpha[{i}] 须在 (90,180)"
    assert all(P["neck_half"][i] > P["neck_half"][i + 1] for i in range(N)), \
        "neck_half 须严格递减（从内到外逐渐扩大）"


# ── 尖角骨架（颈部斜线 + 连接线共线）──

def _tooth_skeleton(P):
    """布局：所有齿根/降面终点/连接线端点落在颈部斜线 X_neck(Y) 上。

    Phase1 用角度计算各点 Y（径向）；Phase2 用颈部斜线（穿过第一个齿根与最后降面终点）
    定各齿根/降面终点/连接线端点的 X（半宽），保证共线。
    """
    n = P["N"]
    nk = P["neck_half"]
    conn = P["neck_platform"]
    ys_root = [-P["H_neck"]]
    ys_tip, ys_plat, ys_under, ys_conn = [], [], [], []
    y = -P["H_neck"]
    for i in range(n):
        h = P["tooth_height"][i]
        thick = P["tooth_thickness"][i]
        beta = math.radians(P["beta"][i])
        alpha = math.radians(P["alpha"][i])
        dy_ext = h * math.tan(beta)                       # 升面 Y 跨度
        y_tip = y - dy_ext
        y_plat = y_tip - thick                            # 平台 Y 跨度
        dx_under = h + nk[i] - nk[i + 1]                  # 降面 X 跨度（名义）
        dy_under = dx_under * (-math.tan(alpha))          # alpha>90 → 正
        y_under = y_plat - dy_under
        y_conn = y_under - conn                           # 连接线 Y 跨度
        ys_tip.append(y_tip); ys_plat.append(y_plat)
        ys_under.append(y_under); ys_conn.append(y_conn)
        ys_root.append(y_conn)
        y = y_conn
    # 颈部斜线 X_neck(Y)：穿过 (nk[0], ys_root[0]) 与 (nk[n], ys_under[n-1])
    Y0, X0 = ys_root[0], nk[0]
    Y1, X1 = ys_under[n - 1], nk[n]

    def x_neck(yy):
        if abs(Y1 - Y0) < 1e-9:
            return X0
        return X0 + (X1 - X0) * (yy - Y0) / (Y1 - Y0)

    return dict(ys_root=ys_root, ys_tip=ys_tip, ys_plat=ys_plat,
                ys_under=ys_under, ys_conn=ys_conn, x_neck=x_neck)


def _build_half_vertices(P):
    """右半边尖角顶点序列：[A0, root0, crest0, plat0, under0, root1, ..., under_{n-1}, conn_last,
    底部外扩 B_flare, 底部平台 B_plat, 根部收窄 B_tip]。

    under_i = 降面终点（连接线起点）；root_{i+1} = 连接线终点 = 下一齿根。
    槽底（卡榫状）：conn_last → 外扩到平台半宽 → 平台（径向）→ 收窄 → 中心平底（镜像闭合）。
    """
    sk = _tooth_skeleton(P)
    n = P["N"]
    x_neck = sk["x_neck"]
    A0 = (P["W_open"] / 2.0, 0.0)
    verts = [A0]
    for i in range(n):
        rx = x_neck(sk["ys_root"][i])
        cx = rx + P["tooth_height"][i]
        verts.append((rx, sk["ys_root"][i]))                    # root_i
        verts.append((cx, sk["ys_tip"][i]))                     # crest_i
        verts.append((cx, sk["ys_plat"][i]))                    # plat_i（平台终点）
        verts.append((x_neck(sk["ys_under"][i]), sk["ys_under"][i]))  # under_i
    # 最后连接线终点（在颈部斜线上）
    y_conn_last = sk["ys_conn"][-1]
    conn_last = (x_neck(y_conn_last), y_conn_last)
    verts.append(conn_last)
    # 卡榫状槽底：外扩 → 平台 → 根部收窄
    Wb = P["bottom_half_width"]
    flare = math.radians(P["bottom_flare_angle"])
    dy_flare = (Wb - conn_last[0]) / math.tan(flare) if flare > 0.001 else 0.0
    B_flare = (Wb, conn_last[1] - dy_flare)
    verts.append(B_flare)
    B_plat = (Wb, B_flare[1] - P["bottom_platform"])
    verts.append(B_plat)
    B_tip = (P["bottom_tip_half"], B_plat[1] - P["bottom_tip_depth"])
    verts.append(B_tip)
    return verts, sk


def _plan_fillets(P, verts):
    """构建圆角方案：(角点索引 → 半径) + 共享线段协调（每段两端切点距离之和 ≤ 段长）。"""
    n = P["N"]
    conn_idx = len(verts) - 4      # 最后连接线终点 conn_last
    flare_idx = len(verts) - 3     # 外扩终点
    plat_idx = len(verts) - 2      # 平台终点
    tip_idx = len(verts) - 1       # 根部收窄终点
    corners = [(1, (verts[0], verts[1], verts[2]), P["R_neck"])]
    for i in range(n):
        ri, ci, pi, ui = 1 + 4 * i, 2 + 4 * i, 3 + 4 * i, 4 + 4 * i
        nxt = 1 + 4 * (i + 1) if i < n - 1 else conn_idx      # root_{i+1} 或 conn_last
        corners.append((ci, (verts[ri], verts[ci], verts[pi]), P["Rc"][i]))       # 齿顶
        corners.append((pi, (verts[ci], verts[pi], verts[ui]), P["Rt"][i]))       # 齿根平台
        corners.append((ui, (verts[pi], verts[ui], verts[nxt]), P["Rr"][i]))      # 连接线上端
        if i < n - 1:
            ri_next = 1 + 4 * (i + 1)
            ci_next = 2 + 4 * (i + 1)
            corners.append((ri_next, (verts[ui], verts[ri_next], verts[ci_next]),
                            P["Rr"][i]))                       # 连接线下端（齿根凹口）
    # 卡榫状槽底圆角
    corners.append((conn_idx, (verts[conn_idx - 1], verts[conn_idx], verts[flare_idx]),
                    P["R_shoulder"]))                          # 连接线→外扩壁
    corners.append((flare_idx, (verts[conn_idx], verts[flare_idx], verts[plat_idx]),
                    P["R_flare"]))                             # 外扩壁→平台
    corners.append((plat_idx, (verts[flare_idx], verts[plat_idx], verts[tip_idx]),
                    P["R_plat"]))                              # 平台→收窄壁
    # 根部收窄→中心平底（R_tip）：P2 = 中心平底的镜像点（跨轴，build_slot2d 应用）
    corners.append((tip_idx, (verts[plat_idx], verts[tip_idx],
                              (-verts[tip_idx][0], verts[tip_idx][1])), P["R_tip"]))

    n_edges = len(verts) - 1
    geoms = []
    edge_span = [0.0] * n_edges
    for idx, tri, R in corners:
        g = _fillet_geom(*tri, R)
        if g is None:
            geoms.append((idx, None, None, None))
            continue
        T1, T2, s1, s2, C, a1, da, R = g
        geoms.append((idx, R, -s1, s2))
        edge_span[idx - 1] += -s1
        if idx < n_edges:                # R_tip 的 s2 落在虚拟平底边（镜像），不参与协调
            edge_span[idx] += s2
    edge_len = [_norm(_vec(verts[k], verts[k + 1])) for k in range(n_edges)]
    allowed = [min(1.0, edge_len[k] / edge_span[k]) if edge_span[k] > 1e-9 else 1.0
               for k in range(n_edges)]
    radii = [None] * len(verts)
    for idx, R, sp1, sp2 in geoms:
        if R is None:
            continue
        sc = allowed[idx - 1]
        if idx < n_edges:
            sc = min(sc, allowed[idx])
        radii[idx] = R * min(1.0, sc)
    return radii


def _emit(P, verts, radii):
    """按顶点序列输出轮廓点（圆角替换尖角，直线段连接）。"""
    pts = []

    def _push(p):
        if pts and math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) < 1e-4:
            return
        pts.append(p)

    _push(verts[0])
    for k in range(1, len(verts) - 1):
        R = radii[k]
        if R:
            g = _fillet_geom(verts[k - 1], verts[k], verts[k + 1], R)
            if g:
                _push(g[0])
                for p in _arc_points(g):
                    _push(p)
            else:
                _push(verts[k])
        else:
            _push(verts[k])
    _push(verts[-1])
    return pts


def build_right_half(P):
    """右半边轮廓点（从槽口 A0 到槽底中心 X=0）。"""
    _validate(P)
    verts, sk = _build_half_vertices(P)
    radii = _plan_fillets(P, verts)
    return _emit(P, verts, radii)


def build_slot2d(P):
    """完整二维榫槽：右半边 → X=0 镜像 → 闭合（底部中心平底，顶部 = 口部线）。

    槽底（卡榫状）R_tip：根部收窄壁与中心平底的夹角在 build 后做圆弧 R_tip
    （P2 = 平底镜像点），圆弧跨对称轴；left = 镜像（从弧端向上到左口部）。
    """
    _validate(P)
    verts, sk = _build_half_vertices(P)
    radii = _plan_fillets(P, verts)
    right = _emit(P, verts, radii)          # [A0, ..., B_plat, B_tip]

    B_tip = right[-1]
    p0 = right[-2]                          # 收窄壁上一点（B_plat 或其圆角切点）
    g = _fillet_geom(p0, B_tip, (-B_tip[0], B_tip[1]), P["R_tip"])
    if g:
        arc = _arc_points(g)                # [T1(收窄壁), ..., T2(平底)]，跨轴
        right = right[:-1] + [arc[0]] + arc[1:]
    left = [(-x, y) for (x, y) in reversed(right)]
    return left + right


def report(P, pts):
    """打印结构测量：点距 / 颈部斜线共线检查 / 齿凸出 / 槽底。"""
    n = P["N"]
    sk = _tooth_skeleton(P)
    right = pts[len(pts) // 2:]
    print(f"total={len(pts)}pts  depth={abs(right[-1][1]):.2f}mm  mouth={P['W_open']}mm")
    x_neck = sk["x_neck"]
    xs_line = [x_neck(y) for y in sk["ys_root"][:-1] + sk["ys_under"]]
    xs_line.append(x_neck(sk["ys_conn"][-1]))
    print("neck-line pts X (collinear):", " -> ".join(f"{v:.3f}" for v in xs_line))
    for i in range(n):
        dep = abs(sk["ys_root"][i + 1] - sk["ys_root"][i])
        gam = 180.0 - P["alpha"][i]
        print(f"tooth{i+1}: rootX={x_neck(sk['ys_root'][i]):.2f} crestX={x_neck(sk['ys_root'][i])+P['tooth_height'][i]:.2f} "
              f"depth={dep:.2f}  非承力边(升面)β={P['beta'][i]:.0f}° > 承力边(降面)γ={gam:.0f}°  "
              f"conn=({x_neck(sk['ys_conn'][i]):.2f},{sk['ys_conn'][i]:.2f})")
    # 卡榫状槽底
    conn_last = (x_neck(sk["ys_conn"][-1]), sk["ys_conn"][-1])
    Wb = P["bottom_half_width"]
    dyf = (Wb - conn_last[0]) / math.tan(math.radians(P["bottom_flare_angle"]))
    print(f"bottom(卡榫): conn({conn_last[0]:.2f},{conn_last[1]:.2f}) → flare {Wb:.2f} → "
          f"platform {P['bottom_platform']:.1f} → tip {P['bottom_tip_half']:.1f} "
          f"(R_shoulder={P['R_shoulder']:.2f} R_flare={P['R_flare']:.2f} "
          f"R_plat={P['R_plat']:.2f} R_tip={P['R_tip']:.2f})")
    mins = min(_norm(_vec(pts[i], pts[i + 1])) for i in range(len(pts) - 1))
    i_min = min(range(len(pts) - 1), key=lambda i: _norm(_vec(pts[i], pts[i + 1])))
    print(f"min_pt_gap={mins:.4f} @({pts[i_min][0]:.2f},{pts[i_min][1]:.2f})  (should >0.02)")
    # 对称性：每个点都可在点集中找到其关于 X=0 的镜像（跨轴圆底不破坏对称）
    def _mirrored():
        for p in pts:
            if not any(abs(p[0] + q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6 for q in pts):
                return False
        return True
    print(f"symmetry: {'OK' if _mirrored() else 'FAIL'}  (closed at ({pts[0][0]:.2f},{pts[0][1]:.2f}))")


# ── 绘制 ──────────────────────────────────────────────────────

def plot(P, pts, out="output/fir_tree_slot2d_annotated.png"):
    xs = [p[0] for p in pts] + [pts[0][0]]
    ys = [p[1] for p in pts] + [pts[0][1]]
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.plot(xs, ys, "-", color="#1f77b4", lw=1.5)
    ax.plot(xs, ys, "o", color="#d62728", ms=5)
    for i, (x, y) in enumerate(pts):
        ax.annotate(str(i), (x, y), textcoords="offset points",
                    xytext=(5, 6), fontsize=8, color="#d62728")
    ax.axhline(0, color="gray", lw=0.6, ls="--")
    ax.axvline(0, color="gray", lw=0.6, ls="--")
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    ax.set_title(f"Fir-tree slot 2D ({len(pts)} pts, N={P['N']}, depth={abs(pts[0][1]):.1f})")
    ax.set_xlabel("X (circumferential, mm)")
    ax.set_ylabel("Y (radial inward, mm)")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print("saved:", out, len(pts), "pts")


if __name__ == "__main__":
    P = make_params(N=3)
    prof = build_slot2d(P)
    report(P, prof)
    plot(P, prof)
    for i, p in enumerate(prof):
        print("%2d (%6.2f, %7.2f)" % (i, p[0], p[1]))
