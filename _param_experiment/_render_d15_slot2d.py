# -*- coding: utf-8 -*-
"""一次性：D15 榫槽 2D 截面图（真实圆角），供人工精确检查齿形/卡榫底/角度。

用法: .conda/python.exe _param_experiment/_render_d15_slot2d.py
产物: _param_experiment/output/d15_slot_section.png
"""
import sys
sys.path.insert(0, r'E:\text_to_cad_improve\auto_detection_process\_param_experiment')
import param_templates as pt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False
OUT = r'E:\text_to_cad_improve\auto_detection_process\_param_experiment\output'


def build_real_fillet(params):
    doc = pt.build(params)
    pts, fillets = None, []
    for nd in doc['nodes']:
        if nd.get('component') != 'slot_cutter':
            continue
        if nd['op'] == 'add_polyline':
            pts = [(p['x_mm'], p['y_mm']) for p in nd['params']['points']]
        elif nd['op'] == 'fillet_sketch':
            fillets.append((nd['params']['radius_mm'], nd['params']['at_vertex_index']))
    if pts is None:
        return None, None, None
    import fir_tree_slot2d as f2
    n = len(pts)
    per = {}
    for radius, idxs in fillets:
        for vi in idxs:
            per[int(vi)] = float(radius)
    out = []
    for i in range(n):
        R = per.get(i)
        if R:
            g = f2._fillet_geom(pts[i - 1], pts[i], pts[(i + 1) % n], R)
            if g:
                arc = f2._arc_points(g, npts=7)
                if not out or (out[-1][0] - arc[0][0]) ** 2 + (out[-1][1] - arc[0][1]) ** 2 > 1e-12:
                    out.append(arc[0])
                out.extend(arc[1:])
            else:
                out.append(pts[i])
        else:
            out.append(pts[i])
    return pts, out, fillets


params = dict(
    od_mm=500, bore_mm=120, thick_mm=76, hub_mm=38, rim_mm=30,
    teeth=2, R_mm=215, depth_mm=21.2, throat_half_width_mm=8.0, fr_mm=0.97,
    category='slot', form='standard', disc_fillet_mm=10.0, _tag='d15_v9',
    tfa_deg=45.0, ufa_deg=75.0)
lim = pt.slot_fillet_fr_limit(2, 21.2, 8.0, 45.0, 75.0)
params['fr_mm'] = min(params['fr_mm'], lim)
pts, real, fillets = build_real_fillet(params)
print(f"fr_limit={lim:.2f}  fr_used={params['fr_mm']:.2f}")
print(f"骨架点={len(pts)} 圆角节点数={len(fillets)}")

# 连接线斜率：颈部斜线上两相邻齿根点（y 半宽, x 径向）
n_upper = len(pts) // 2
# 找连接线（每齿 5+4i 与下一齿根）—— 用骨架点验证共线
xs = [p[0] for p in pts[:n_upper]]
ys = [p[1] for p in pts[:n_upper]]
rads = sorted({round(r, 2) for r, _ in fillets})

fig, axes = plt.subplots(1, 2, figsize=(15, 6.2))
# 左：全槽轮廓
ax = axes[0]
rx = [p[0] for p in real] + [real[0][0]]
ry = [p[1] for p in real] + [real[0][1]]
ax.plot(rx, ry, '-', color='#1f77b4', lw=1.6, label='真实圆角轮廓')
sx = [p[0] for p in pts]; sy = [p[1] for p in pts]
ax.plot(sx, sy, 'x', color='#d62728', ms=4, alpha=0.5, label='尖角骨架')
ax.set_title(f'D15 榫槽截面 (teeth=2, depth=21.2, throat=8)\nfr={params["fr_mm"]:.2f} 圆角半径 {rads}\n'
             f'slot2d 自然结构·连接线 1.25mm·卡榫紧凑·neck=[0.84,0.64,0.44]m', fontsize=10)
ax.set_aspect('equal'); ax.grid(alpha=0.3); ax.axhline(0, color='gray', lw=0.5, ls='--')
ax.legend(fontsize=8)
ax.set_xlabel('径向 x (mm, 0=槽口)'); ax.set_ylabel('半宽 y (mm)')

# 右：半槽放大 + 标注角度
ax2 = axes[1]
half = real[:len(real) // 2 + 1]
hx = [p[0] for p in half] + [half[0][0]]
hy = [p[1] for p in half] + [half[0][1]]
ax2.plot(hx, hy, '-o', color='#1f77b4', lw=1.8, ms=2)
hsx = [p[0] for p in pts[:n_upper]]; hsy = [p[1] for p in pts[:n_upper]]
ax2.plot(hsx, hsy, 'x', color='#d62728', ms=5, alpha=0.6)
# 斜面斜率示意：找齿顶(半宽最大)与相邻齿根
# 升面(非承力 45°) 与 降面(承力 75° 与径向)
ax2.set_title(f'半槽放大 (上侧)\n升面≈45°(非承力) 降面≈75°与径向(承力/缓)', fontsize=10)
ax2.set_aspect('equal'); ax2.grid(alpha=0.3)
ax2.set_xlabel('径向 x (mm)'); ax2.set_ylabel('半宽 y (mm)')
fig.suptitle('D15 v9 涡轮盘榫槽 2D 截面（slot2d 自然结构，真实圆角）', fontsize=13)
fig.tight_layout()
fig.savefig(OUT + r'\d15_v9_slot_section.png', dpi=150)
print('saved:', OUT + r'\d15_v9_slot_section.png')
