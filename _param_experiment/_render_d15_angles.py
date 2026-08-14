# -*- coding: utf-8 -*-
"""D15 不同齿面角组合样例：榫槽截面对比 + 代表性组合 STEP（不覆盖原 D15）。

用法: .conda/python.exe _param_experiment/_render_d15_angles.py
产物: _param_experiment/output/d15_angle_compare.png
"""
import sys, os, json
sys.path.insert(0, r'E:\text_to_cad_improve\auto_detection_process\_param_experiment')
sys.path.insert(0, r'E:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server')
sys.path.insert(0, r'E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src')
import param_templates as pt
import fir_tree_slot2d as f2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False
OUT = r'E:\text_to_cad_improve\auto_detection_process\_param_experiment\output'

# D15 基参（与 design_families 一致）
BASE = dict(od_mm=500, bore_mm=120, thick_mm=76, hub_mm=38, rim_mm=30,
            slots=40, teeth=2, R_mm=215, depth_mm=21.2, throat_half_width_mm=8.0,
            fr_mm=0.97, category='slot', form='standard')


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


# 齿面角组合（β=升面/非承力与半宽夹角 90-tfa，γ=降面/承力 90-ufa）
ANGLES = [(45, 75, '默认 45°/75° (β=45°, γ=15°)'),
          (40, 80, '更极端 40°/80° (β=50°, γ=10°)'),
          (50, 70, '较缓 50°/70° (β=40°, γ=20°)'),
          (35, 85, '极端 35°/85° (β=55°, γ=5°)')]

fig, axes = plt.subplots(2, 2, figsize=(14, 11))
for idx, (tfa, ufa, label) in enumerate(ANGLES):
    ax = axes[idx // 2][idx % 2]
    params = {**BASE, 'tfa_deg': float(tfa), 'ufa_deg': float(ufa), '_tag': f'd15_a{tfa}_{ufa}'}
    fl = pt.slot_fillet_fr_limit(2, 21.2, 8.0, tfa, ufa)
    params['fr_mm'] = min(params['fr_mm'], fl)
    pts, real, fillets = build_real_fillet(params)
    if real is None:
        ax.set_title(f'{label}\nFAILED', fontsize=9)
        ax.axis('off')
        continue
    xs = [p[0] for p in real] + [real[0][0]]
    ys = [p[1] for p in real] + [real[0][1]]
    ax.plot(xs, ys, '-', color='#1f77b4', lw=1.6)
    sx = [p[0] for p in pts]; sy = [p[1] for p in pts]
    ax.plot(sx, sy, 'x', color='#d62728', ms=4, alpha=0.5)
    rads = sorted({round(r, 2) for r, _ in fillets})
    ax.set_title(f'{label}\nfr_used={params["fr_mm"]:.2f} 圆角{rads}', fontsize=9)
    ax.set_aspect('equal'); ax.grid(alpha=0.3); ax.axhline(0, color='gray', lw=0.5, ls='--')
fig.suptitle('D15 不同齿面角组合（mouth=8, depth=21.2, slots=40）— 不覆盖原 D15', fontsize=13)
fig.tight_layout()
out = OUT + r'\d15_angle_compare.png'
fig.savefig(out, dpi=140)
print('saved:', out)

# 代表性组合（更极端 40/80）生成完整 STEP 样例
import main
params = {**BASE, 'tfa_deg': 40.0, 'ufa_deg': 80.0, '_tag': 'd15_ang40_80'}
tid = 'check_D15_ang40_80'
out_dir = main.OUT_ROOT / tid
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / 'llm_raw.json').write_text(
    json.dumps(pt.build(params), ensure_ascii=False, indent=2), encoding='utf-8')
os.environ['TEMPLATE_L2'] = '1'
text = '生成一个高压涡轮盘参考几何：轮毂-腹板-轮缘盘体，带枞树形榫槽。'
main._tasks[tid] = {'taskId': tid, 'status': 'pending', 'progress': 0, 'result': None, 'error': None}
main._run_pipeline(tid, text, force_route='generative_cad_ir')
d = json.loads((out_dir / 'pipeline_log.json').read_text(encoding='utf-8'))
print(f'{tid}:', 'OK' if d.get('ok') else 'FAIL ' + str(d.get('error')))
print('STEP:', out_dir / 'output.step')
