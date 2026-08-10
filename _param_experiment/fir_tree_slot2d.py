"""枞树形榫槽二维参数化生成器 — 参考 docs/榫槽伪代码.md。

方法（文档 §20-21）：
  BuildSharpHalfProfile（尖角骨架）→ CreateFillet（圆角相切）→ Trim →
  Mirror（X=0 镜像）→ Close（顶部线 + 底部圆弧）→ 绘制标注点号。

坐标系（文档 §1/§10）：X 周向（右半边 X>0），Y 径向（向深处 -Y），X=0 对称中心线。
角度以 +X 为 0°，PointByAngleLength: (x+L·cosθ, y−L·sinθ)。
非承载面角 beta（x 增）、承载面角 alpha（x 减，>90°）。
"""
from __future__ import annotations

import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ── 基本几何函数 ───────────────────────────────────────────────

def _pba(P0, L, theta_deg):
    """PointByAngleLength：P0 沿 theta 方向（与 +X 夹角）延伸 L。Y 向深处为 -Y。"""
    t = math.radians(theta_deg)
    return (P0[0] + L * math.cos(t), P0[1] - L * math.sin(t))


def _vec(a, b):
    return (b[0] - a[0], b[1] - a[1])


def _norm(v):
    return math.hypot(v[0], v[1])


def fillet(P0, P1, P2, R, npts=9):
    """尖角 P0→P1→P2 处做半径 R 圆角，返回 [T1, 圆弧点..., T2]。

    切点距 = R/tan(φ/2)，φ 为两线夹角；圆心在角平分线方向距 P1 = R/sin(φ/2)。
    T1 在 LineA(P0→P1) 上，T2 在 LineB(P1→P2) 上，圆弧 T1→T2。
    """
    vA = _vec(P0, P1)  # P0→P1（轮廓走向，LineA 方向）
    vB = _vec(P1, P2)  # P1→P2
    lA, lB = _norm(vA), _norm(vB)
    if lA < 1e-9 or lB < 1e-9:
        return None
    uA = (vA[0] / lA, vA[1] / lA)
    uB = (vB[0] / lB, vB[1] / lB)
    cos_phi = max(-1.0, min(1.0, uA[0] * uB[0] + uA[1] * uB[1]))
    phi = math.acos(cos_phi)
    if phi < 1e-3 or phi > math.pi - 1e-3:
        return None
    td = R / math.tan(phi / 2.0)
    if td > lA or td > lB:   # 切点超出邻边 → 圆角超界，跳过
        return None
    # 切点：T1 沿 uA（P1→P0 方向）回退 td，T2 沿 uB（P1→P2）前进 td
    T1 = (P1[0] - td * uA[0], P1[1] - td * uA[1])
    T2 = (P1[0] + td * uB[0], P1[1] + td * uB[1])
    # 圆心：T1 沿 LineA 法向 R（朝内角侧，即 T2 所在侧）——保证 T1 在圆上
    nx, ny = -uA[1], uA[0]   # uA(P1→P0) 的 90° 旋转
    if nx * (T2[0] - P1[0]) + ny * (T2[1] - P1[1]) < 0:
        nx, ny = -nx, -ny
    C = (T1[0] + R * nx, T1[1] + R * ny)
    # 圆弧点 T1→T2（绕 C，内角 φ）
    a1 = math.atan2(T1[1] - C[1], T1[0] - C[0])
    a2 = math.atan2(T2[1] - C[1], T2[0] - C[0])
    # 保证沿内角方向（弧角 = φ）
    da = (a2 - a1) % (2 * math.pi)
    if da > math.pi:
        da -= 2 * math.pi
    arc = []
    for k in range(1, npts):
        a = a1 + da * k / (npts - 1.0)
        arc.append((C[0] + R * math.cos(a), C[1] + R * math.sin(a)))
    return [T1] + arc + [T2]


# ── 参数结构（文档 §25）── ─────────────────────────────────────

def make_params(N=3, **over):
    base = {
        "N": N,
        "W_open": 8.0, "W_neck": 5.0, "H_neck": 3.0,
        "R_neck": 1.0,                       # 上过渡圆角
        "Tooth": [{"alpha": 115.0, "beta": 65.0, "La": 5.0, "Lb": 5.0,
                   "Rc": 1.5, "Rt": 1.0}] * N,
        "W_bottom": 3.0, "H_bottom": 4.0, "R_bottom": 0.3,
    }
    base.update(over)
    return base


# ── 右半边尖角骨架 + 圆角 → 轮廓点 ─────────────────────────────

def build_right_half(P):
    """右半边轮廓点序列（从槽口 A0 到槽底中心线 X=0），含圆角圆弧点，相邻点去重。"""
    N = P["N"]
    A0 = (P["W_open"] / 2.0, 0.0)
    A1 = (P["W_neck"] / 2.0, -P["H_neck"])
    T = P["Tooth"]
    pts = [A0]

    def _push(p):
        if pts and math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) < 1e-4:
            return
        pts.append(p)

    def _push_seq(seq):
        for p in seq:
            _push(p)

    # 每齿尖角骨架（unload: cur→B，load: B→C）
    teeth = []
    cur = A1
    for i in range(N):
        B = _pba(cur, T[i]["Lb"], T[i]["beta"])
        C = _pba(B, T[i]["La"], T[i]["alpha"])
        teeth.append({"un0": cur, "B": B, "C": C})
        cur = C

    # 轮廓拓扑：neck(A0→A1) → R_neck → unload0 → Rc0 → load0 → Rt0 → unload1 → ...
    # 1) R_neck（neck 与 unload[0] 交于 A1）
    neck_un0 = fillet(A0, A1, teeth[0]["B"], P["R_neck"])
    if neck_un0:
        _push_seq(neck_un0)
    else:
        _push(A1)
    # 2) 每齿：齿顶 Rc（unload 与 load 交于 B）、齿根 Rt（load 与下一 unload 交于 C）
    for i in range(N):
        un0, B, C = teeth[i]["un0"], teeth[i]["B"], teeth[i]["C"]
        crest = fillet(un0, B, C, T[i]["Rc"])
        if crest:
            _push_seq(crest)
        else:
            _push(B)
        if i < N - 1:
            root = fillet(B, C, teeth[i + 1]["B"], T[i]["Rt"])
            if root:
                _push_seq(root)
            else:
                _push(C)
    # 3) 底部：最后承载面 → R_bottom 圆角 → 底部侧线 → 槽底中心 (0, y_bottom)
    last_B, last_C = teeth[-1]["B"], teeth[-1]["C"]
    y_bottom = last_C[1] - P["H_bottom"]
    bottom_side = (P["W_bottom"] / 2.0, y_bottom)
    bot = fillet(last_B, last_C, bottom_side, P["R_bottom"])
    if bot:
        _push_seq(bot)
    else:
        _push(bottom_side)
    _push((0.0, y_bottom))
    return pts


def build_slot2d(P):
    """完整二维榫槽：右半边 → 镜像 → 顶部闭合。返回闭合点序列。"""
    right = build_right_half(P)
    left = [(-x, y) for (x, y) in reversed(right[1:-1])]  # 镜像（去首尾重复）
    # 顶部线：左口部(-W_open/2, 0) → 右口部(W_open/2, 0)
    profile = left + right
    return profile


# ── 绘制 ──────────────────────────────────────────────────────

def plot(pts, out="output/fir_tree_slot2d_annotated.png"):
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
    ax.set_title(f"Fir-tree slot 2D ({len(pts)} pts, N={sum(1 for _ in range(10))})")
    ax.set_xlabel("X (circumferential, mm)")
    ax.set_ylabel("Y (radial inward, mm)")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print("saved:", out, len(pts), "pts")


if __name__ == "__main__":
    P = make_params(N=3)
    prof = build_slot2d(P)
    plot(prof)
    for i, p in enumerate(prof):
        print("%2d (%6.2f, %6.2f)" % (i, p[0], p[1]))
