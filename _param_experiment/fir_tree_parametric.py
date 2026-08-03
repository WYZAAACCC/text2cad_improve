"""枞树形榫槽 — 确定性参数化轮廓生成器（ground truth，隔离实验）。

从完整参数（每齿独立齿高/齿厚/齿面角/圆角 + 齿间楔形斜面）直接计算轮廓点。
与 LLM 输出格式一致（点序列），便于对比。

用法:
  .conda/python.exe _param_experiment/fir_tree_parametric.py
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parent / "output" / "parametric_gt"
OUT.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class FirTreeParams:
    """完整枞树榫槽参数（HB5965 体系）。"""

    teeth_count: int
    slot_depth_mm: float
    mouth_half_width_mm: float = 4.0
    mouth_wedge_dx_mm: float = 3.0              # 口部楔形径向跨度
    tooth_height_mm: list = field(default_factory=list)      # 每齿齿高（径向跨度，应越远离圆心越高=数组从大到小）
    tooth_thickness_mm: list = field(default_factory=list)   # 每齿节线处齿厚
    top_flank_angle_deg: list = field(default_factory=list)  # 每齿工作面角（与径向夹角）
    under_flank_angle_deg: list = field(default_factory=list)  # 每齿非工作面角
    neck_half_width_mm: list = field(default_factory=list)   # 每齿颈部半宽（len=teeth_count+1）
    neck_platform_mm: float = 1.0                            # 齿间颈部水平平台长度
    tip_fillet_mm: list = field(default_factory=list)        # 每齿齿端圆角（元数据）
    root_fillet_mm: list = field(default_factory=list)       # 每齿齿根圆角（元数据）
    bottom_half_width_mm: float = 3.0
    bottom_platform_mm: float = 1.0            # 槽底水平平台 x 宽（对照 A：1mm）
    bottom_flare_angle_deg: float = 60.0       # 底部外扩角（越大越陡，13→14 越近）
    bottom_fillet_mm: float = 0.8

    def __post_init__(self):
        n = self.teeth_count
        assert len(self.tooth_height_mm) == n, "tooth_height 长度须=teeth_count"
        assert len(self.tooth_thickness_mm) == n, "tooth_thickness 长度须=teeth_count"
        assert len(self.top_flank_angle_deg) == n, "top_flank 长度须=teeth_count"
        assert len(self.under_flank_angle_deg) == n, "under_flank 长度须=teeth_count"
        assert len(self.neck_half_width_mm) == n + 1, "neck_half_width 长度须=teeth_count+1"
        # 补齐 fillet（可为空 → 全 0.5）
        if not self.tip_fillet_mm:
            object.__setattr__(self, "tip_fillet_mm", [0.5] * n)
        if not self.root_fillet_mm:
            object.__setattr__(self, "root_fillet_mm", [0.4] * n)


def generate_profile(p: FirTreeParams) -> list[dict]:
    """生成一侧（y≥0）轮廓点，从槽口 (0) 向内。

    几何定义（对齐 A 组合参考 + 用户修改）：
      - tooth_height_mm[i] = 齿的 **y 方向凸出高度**（w_tip - w_neck）
      - 外斜面 x 跨度 = h_y / tan(top_flank_angle)；内斜面 x 跨度 = (h_y + w_neck - w_next) / tan(under_flank)
      - 齿顶平台 x 宽 = tooth_thickness
      - **连接线**（齿间颈部段）沿**颈部斜线**倾斜（两端 y 不同，非水平），长度 = neck_platform_mm
      - 颈部斜线：所有齿根点共线（越向外 y 越大，上侧；下侧相反）
      - 底部：内斜面 → 最后颈部 → 底部外扩 → 槽底平台(宽) → 根部

    两阶段：先算布局(x)，再用颈部斜线 y_neck(x) 定各齿根 y。
    """
    n = p.teeth_count
    conn = max(p.neck_platform_mm, 0.0)  # 连接线长度

    # === Phase 1: 布局（用标称 neck 计算各齿 x 位置）===
    xs_root: list[float] = []   # 各齿外斜面起点（齿根）
    xs_tip: list[float] = []
    xs_tip_end: list[float] = []
    xs_neck: list[float] = []   # 各内斜面终点（齿根）
    x = -p.mouth_wedge_dx_mm
    xs_root.append(x)
    for i in range(n):
        h_y = p.tooth_height_mm[i]
        thick = p.tooth_thickness_mm[i]
        theta_work = math.radians(p.top_flank_angle_deg[i])
        theta_back = math.radians(p.under_flank_angle_deg[i])
        dx_work = h_y / math.tan(theta_work) if theta_work > 0.001 else 0.0
        x_tip = x - dx_work
        xs_tip.append(x_tip)
        x_tip_end = x_tip - thick
        xs_tip_end.append(x_tip_end)
        if i < n - 1:
            w_neck_n = p.neck_half_width_mm[i]
            w_next_n = p.neck_half_width_mm[i + 1]
            dx_back = (h_y + w_neck_n - w_next_n) / math.tan(theta_back) if theta_back > 0.001 else thick
            x_next = x_tip_end - dx_back
            xs_neck.append(x_next)
            x_work = x_next - conn
            xs_root.append(x_work)
            x = x_work
        else:
            # 最后一个齿：内斜面也有 x 跨度（到"最后颈部"）
            w_neck_n = p.neck_half_width_mm[i]
            w_next_n = p.neck_half_width_mm[i + 1]
            dx_back = (h_y + w_neck_n - w_next_n) / math.tan(theta_back) if theta_back > 0.001 else thick
            x_neck = x_tip_end - dx_back
            xs_neck.append(x_neck)

    # 颈部斜线 y_neck(x)：穿过第一个齿根(neck[0]) 和最后颈部(neck[n])（线性）
    x0, y0 = xs_root[0], p.neck_half_width_mm[0]
    x1, y1 = xs_neck[-1], p.neck_half_width_mm[n]

    def y_neck(xx: float) -> float:
        if abs(x1 - x0) < 1e-6:
            return y0
        return y0 + (y1 - y0) * (xx - x0) / (x1 - x0)

    # === Phase 2: 生成点（y 用颈部斜线）===
    pts: list[tuple[float, float]] = []

    def add(pt):
        if not pts or abs(pt[0] - pts[-1][0]) > 1e-6 or abs(pt[1] - pts[-1][1]) > 1e-6:
            pts.append(pt)

    # 口部
    add((0.0, p.mouth_half_width_mm))
    add((xs_root[0], y_neck(xs_root[0])))  # 口部楔形 → 颈部1（斜线）

    for i in range(n):
        h_y = p.tooth_height_mm[i]
        thick = p.tooth_thickness_mm[i]
        w_neck = y_neck(xs_root[i])         # 齿根在斜线上
        theta_work = math.radians(p.top_flank_angle_deg[i])
        theta_back = math.radians(p.under_flank_angle_deg[i])

        w_tip = w_neck + h_y
        dx_work = h_y / math.tan(theta_work) if theta_work > 0.001 else 0.0
        x_tip = xs_root[i] - dx_work

        add((xs_root[i], w_neck))           # 外斜面起点（齿根，斜线）
        add((x_tip, w_tip))                 # 外斜面顶

        x_tip_end = x_tip - thick
        add((x_tip_end, w_tip))             # 齿顶平台

        if i < n - 1:
            # 内斜面 → 内斜面终点（齿根，斜线）
            x_neck = xs_neck[i]
            w_neck_next = y_neck(x_neck)
            add((x_neck, w_neck_next))
            # 连接线（斜）：从 (x_neck, w_next) 沿斜线到下一齿外斜面起点
            x_work = xs_root[i + 1]
            w_work = y_neck(x_work)
            add((x_work, w_work))           # 下一齿根（连接线终点）
        else:
            # 最后一个齿：内斜面 → 最后颈部 → 连接线(沿斜线) → 底部外扩 → 槽底平台 → 根部
            x_last_neck = xs_neck[i]
            w_last_neck = y_neck(x_last_neck)
            add((x_last_neck, w_last_neck))          # 最后颈部（斜线）
            # 连接线（沿斜线延伸 conn 长度）→ 与其他齿间连接线一致
            x_conn = x_last_neck - conn
            w_conn = y_neck(x_conn)
            add((x_conn, w_conn))                    # 连接线终点（斜线）
            # 底部外扩（从连接线终点升到槽底半宽，外扩角 bottom_flare_angle）
            w_bottom = p.bottom_half_width_mm
            theta_flare = math.radians(p.bottom_flare_angle_deg)
            dx_rise = (w_bottom - w_conn) / math.tan(theta_flare) if theta_flare > 0.001 else 0.0
            x_bottom = x_conn - dx_rise
            add((x_bottom, w_bottom))       # 槽底（外扩终点）
            x_plat = x_bottom - p.bottom_platform_mm
            add((x_plat, w_bottom))         # 槽底平台
            add((x_plat - 1.0, p.bottom_half_width_mm - 1.5))  # 根部收窄

    # 镜像下侧：关于 y=0 中心线的轴对称（x 不变，仅 y 取负，顺序反转）
    # 错误版本曾用 (-q[0], -q[1]) —— 那是中心对称(180°旋转)，会导致整体错乱
    lower = [(q[0], -q[1]) for q in reversed(pts)]
    full = pts + lower
    return [{"x_mm": round(xx, 3), "y_mm": round(yy, 3)} for xx, yy in full]


def plot_profile(params: FirTreeParams, pts: list[dict], title: str, out_path: Path) -> None:
    xs = [p["x_mm"] for p in pts] + [pts[0]["x_mm"]]
    ys = [p["y_mm"] for p in pts] + [pts[0]["y_mm"]]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(xs, ys, "-o", color="#1f77b4", ms=3, lw=1.5)
    ax.axhline(0, color="gray", lw=0.6, ls="--")
    ax.set_aspect("equal")
    info = (f"teeth={params.teeth_count} depth={params.slot_depth_mm}\n"
            f"h={params.tooth_height_mm} t={params.tooth_thickness_mm}\n"
            f"Tfa={params.top_flank_angle_deg} Ufa={params.under_flank_angle_deg}\n"
            f"neck={params.neck_half_width_mm}")
    ax.set_title(f"{title}\n{info}", fontsize=9)
    ax.set_xlabel("Radial depth x (mm, 0=rim surface)")
    ax.set_ylabel("Half-width y (mm)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ── 验证组合 ───────────────────────────────────────────────────────────────

def main():
    combos = {
        # S0: 两齿·等高5 — 精确对齐 A 组合参考（用于逐点对照验证）
        "S0_2tooth_alignA": FirTreeParams(
            teeth_count=2, slot_depth_mm=24,
            tooth_height_mm=[5, 5],
            tooth_thickness_mm=[2, 2],
            top_flank_angle_deg=[66.7, 66.7],
            under_flank_angle_deg=[60, 60],
            neck_half_width_mm=[2, 2, 2],
            neck_platform_mm=2.0,
            bottom_half_width_mm=3.0,
            bottom_platform_mm=1.0,
        ),
        # S1: 三齿，齿高递增（越靠近圆心越高: 4→5.5→7，最后一个明显最高），对齐 A 的角度
        "S1_3tooth_varied": FirTreeParams(
            teeth_count=3, slot_depth_mm=30,
            tooth_height_mm=[4, 5.5, 7],
            tooth_thickness_mm=[2, 2, 2],
            top_flank_angle_deg=[66.7, 66.7, 66.7],
            under_flank_angle_deg=[60, 60, 60],
            neck_half_width_mm=[2, 2.2, 2.5, 2.5],
            neck_platform_mm=2.0,
            bottom_half_width_mm=3.0,
            bottom_platform_mm=1.0,
            tip_fillet_mm=[0.8, 0.9, 1.0],
            root_fillet_mm=[0.5, 0.6, 0.7],
        ),
        # S1_dec: 三齿，齿高递减（越远离圆心越高: 7→5.5→4，第一个最高）——用户确认方向
        # 颈部斜线(齿根共线 2.6→1.8)、连接线沿斜线、槽底更高更宽(用户修改)
        "S1_dec_3tooth": FirTreeParams(
            teeth_count=3, slot_depth_mm=32,
            tooth_height_mm=[7, 5.5, 4],
            tooth_thickness_mm=[2, 2, 2],
            top_flank_angle_deg=[66.7, 66.7, 66.7],
            under_flank_angle_deg=[60, 60, 60],
            neck_half_width_mm=[2.6, 2.3, 2.0, 1.8],
            neck_platform_mm=2.0,
            bottom_half_width_mm=4.0,
            bottom_platform_mm=2.0,
            bottom_flare_angle_deg=60.0,
        ),
        # S2: 两齿，齿高递增(4.5→6.5，最后一个更高)，陡承力面 + 大圆角（KT787 半圆齿风格）
        "S2_2tooth_steep": FirTreeParams(
            teeth_count=2, slot_depth_mm=24,
            tooth_height_mm=[4.5, 6.5],
            tooth_thickness_mm=[2, 2],
            top_flank_angle_deg=[66.7, 66.7],
            under_flank_angle_deg=[60, 60],
            neck_half_width_mm=[2, 2.5, 2.5],
            neck_platform_mm=2.0,
            bottom_half_width_mm=3.0,
            bottom_platform_mm=1.0,
            tip_fillet_mm=[1.5, 1.5],
            root_fillet_mm=[0.8, 0.8],
        ),
        # S3: 四齿，齿高递增(3.5→5→6.5→8，最后一个最高)，对称齿面角
        "S3_4tooth_sym": FirTreeParams(
            teeth_count=4, slot_depth_mm=32,
            tooth_height_mm=[3.5, 5, 6.5, 8],
            tooth_thickness_mm=[1.5, 1.5, 1.5, 1.5],
            top_flank_angle_deg=[66.7, 66.7, 66.7, 66.7],
            under_flank_angle_deg=[60, 60, 60, 60],
            neck_half_width_mm=[1.5, 1.8, 2.0, 2.2, 2.5],
            neck_platform_mm=1.5,
            bottom_half_width_mm=3.0,
            bottom_platform_mm=1.0,
            tip_fillet_mm=[0.6, 0.7, 0.8, 0.9],
            root_fillet_mm=[0.4, 0.5, 0.6, 0.7],
        ),
    }

    print("=== 确定性生成器验证 ===")
    for name, p in combos.items():
        pts = generate_profile(p)
        n_upper = len(pts) // 2
        print(f"\n[{name}] 总点数={len(pts)} (每侧={n_upper})")
        print("  上侧:", [(pt['x_mm'], pt['y_mm']) for pt in pts[:n_upper]])
        # 校验齿顶半宽 > 颈部半宽（不同齿齿高不同）
        for i in range(p.teeth_count):
            w_neck = p.neck_half_width_mm[i]
            h = p.tooth_height_mm[i]
            tfa = p.top_flank_angle_deg[i]
            w_tip_expected = w_neck + h * math.tan(math.radians(tfa))
            print(f"  齿{i+1}: neck={w_neck} → tip≈{round(w_tip_expected,2)} (齿高{h} 工作面角{tfa}°)")
        plot_profile(p, pts, name, OUT / f"slot_gt_{name}.png")

    print(f"\n产物: {OUT}")
    print("对比图已生成: slot_gt_S1_3tooth_varied.png / S2_2tooth_steep.png / S3_4tooth_sym.png")


if __name__ == "__main__":
    main()
