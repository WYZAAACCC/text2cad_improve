# -*- coding: utf-8 -*-
"""渲染 param_templates 榫槽轮廓经**真实半径**圆角后的草图（多参数组合）。

用 build 的 cutter 尖角骨架 + fillet 节点（radius/at_vertex_index），对每个圆角顶点
用 fir_tree_slot2d._fillet_geom 画真圆弧（与 OCC fillet2D 等价的圆弧几何，radius 为
fr 驱动后的真实半径）。弧按轮廓顺序逐角插入，可靠无乱序。
"""
import sys
sys.path.insert(0, r'E:\text_to_cad_improve\auto_detection_process\_param_experiment')
import param_templates as pt
import fir_tree_slot2d as f2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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
    n = len(pts)
    per = {}
    for radius, idxs in fillets:
        for vi in idxs:
            per[int(vi)] = float(radius)
    # 逐角画真圆弧（fir 圆弧几何，半径=fr 驱动后真实值），按轮廓顺序组装
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


def render(combo):
    params = dict(
        od_mm=combo['od'], bore_mm=120, thick_mm=76, hub_mm=38, rim_mm=30,
        teeth=combo['teeth'], R_mm=combo.get('R', 220), depth_mm=combo['depth'],
        throat_half_width_mm=combo['throat'], fr_mm=combo.get('fr', 1.0),
        category='slot', form='standard', disc_fillet_mm=10.0, _tag=combo['name'],
        tfa_deg=combo.get('tfa', 45.0), ufa_deg=combo.get('ufa', 75.0))
    lim = pt.slot_fillet_fr_limit(combo['teeth'], combo['depth'], combo['throat'],
                                    combo.get('tfa', 45.0), combo.get('ufa', 75.0))
    params['fr_mm'] = min(params['fr_mm'], lim)
    try:
        pts, real, fillets = build_real_fillet(params)
    except Exception as e:
        print(f"[{combo['name']}] FAILED: {type(e).__name__} {str(e)[:80]}")
        return None
    if real is None:
        return None
    return pts, real, fillets, params['fr_mm'], lim


# 深度自适应公式：depth = (0.9×teeth + 1.4)×mouth（每齿深度与齿宽相适应）；N4 平台加厚
combos = [
    dict(name='t3 m5 d20.5', od=540, teeth=3, depth=round((1.0*3+0.8)*5,1), throat=5.0, fr=1.0, tfa=45, ufa=75),
    dict(name='t3 m6 d24.6', od=600, teeth=3, depth=round((1.0*3+0.8)*6,1), throat=6.0, fr=2.0, tfa=45, ufa=75),
    dict(name='t3 m7 d28.7', od=620, teeth=3, depth=round((1.0*3+0.8)*7,1), throat=7.0, fr=2.0, tfa=45, ufa=75),
    dict(name='t4 m5 d25.0', od=560, teeth=4, depth=round((1.0*4+0.8)*5,1), throat=5.0, fr=1.0, tfa=45, ufa=75),
    dict(name='t4 m6 d30.0', od=600, teeth=4, depth=round((1.0*4+0.8)*6,1), throat=6.0, fr=2.0, tfa=45, ufa=75),
    dict(name='t4 m7 d35.0', od=640, teeth=4, depth=round((1.0*4+0.8)*7,1), throat=7.0, fr=2.0, tfa=45, ufa=75),
]
results = [render(c) for c in combos]

fig, axes = plt.subplots(2, 3, figsize=(18, 11))
for idx, (combo, res) in enumerate(zip(combos, results)):
    ax = axes[idx // 3][idx % 3]
    if res is None:
        ax.set_title(f"{combo['name']}\nFAILED", fontsize=9)
        ax.axis('off')
        continue
    pts, real, fillets, fr_used, fr_lim = res
    xs = [p[0] for p in real] + [real[0][0]]
    ys = [p[1] for p in real] + [real[0][1]]
    ax.plot(xs, ys, '-', color='#1f77b4', lw=1.6)
    # 骨架点标注（圆角前尖角）
    sxs = [p[0] for p in pts]; sys2 = [p[1] for p in pts]
    ax.plot(sxs, sys2, 'x', color='#d62728', ms=5, alpha=0.6, label='尖角骨架点')
    rads = sorted({round(r, 2) for r, _ in fillets})
    ax.set_title(f"{combo['name']}\nfr_used={fr_used:.2f} (limit {fr_lim:.2f})\n真实圆角半径: {rads}", fontsize=9)
    ax.set_aspect('equal'); ax.grid(alpha=0.3)
    ax.axhline(0, color='gray', lw=0.5, ls='--')
fig.suptitle('depth=(1.0×teeth+0.8)×mouth 连接线短 + 独立大圆角 — 0 小边', fontsize=13)
fig.tight_layout()
out = OUT + r'\slot_real_fillet_compare.png'
fig.savefig(out, dpi=120)
print('saved:', out)
print('fr 上限:', {c['name']: round(res[4], 2) if res else None for c, res in zip(combos, results)})
