"""Plot test_v18 fir-tree cutter profile — EN only for font compatibility"""
import json, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

with open('E:/auto_detection_process/turbine_disc/test_v18_slots_half_cut/llm_raw.json', encoding='utf-8') as f:
    doc = json.load(f)

cutter_pts, disc_pts = [], []
for n in doc['nodes']:
    if n['op'] == 'add_polyline':
        pts = [(p['x_mm'], p['y_mm']) for p in n['params']['points']]
        if 'cutter' in n['component']: cutter_pts = pts
        else: disc_pts = pts

# Ideal fir-tree with inclined flanks (2 lobe pairs, ~25 deg)
ideal = [
    (0, 4), (-4, 7), (-7, 7), (-10, 4), (-10, 10), (-13, 10),
    (-16, 7), (-16, 4), (-20, 4), (-20, -4), (-16, -4), (-16, -7),
    (-13, -10), (-10, -10), (-10, -4), (-7, -7), (-4, -7), (0, -4),
]

fig, axes = plt.subplots(1, 2, figsize=(16, 7))
fig.patch.set_facecolor('white')

# ── LEFT: Cutter profile comparison ──
ax = axes[0]
# LLM staircase
xs = [p[0] for p in cutter_pts] + [cutter_pts[0][0]]
ys = [p[1] for p in cutter_pts] + [cutter_pts[0][1]]
ax.plot(xs, ys, 'o-', color='#e74c3c', lw=2, ms=5, label='LLM output (staircase, 0 inclined)')
for i, (x, y) in enumerate(cutter_pts):
    ax.annotate(str(i), (x, y), fontsize=6, color='#e74c3c', xytext=(4, 4), textcoords='offset points')

# Ideal fir-tree
ixs = [p[0] for p in ideal] + [ideal[0][0]]
iys = [p[1] for p in ideal] + [ideal[0][1]]
ax.plot(ixs, iys, '--', color='#2ecc71', lw=3, alpha=0.8, label='Correct fir-tree (inclined flanks, ~25 deg)')
for i in range(len(ideal)):
    j = (i + 1) % len(ideal)
    dx, dy = ideal[j][0] - ideal[i][0], ideal[j][1] - ideal[i][1]
    if abs(dx) > 0.01 and abs(dy) > 0.01:
        mx, my = (ideal[i][0] + ideal[j][0]) / 2, (ideal[i][1] + ideal[j][1]) / 2
        angle = np.degrees(np.arctan2(abs(dy), abs(dx)))
        ax.annotate(f'{angle:.0f} deg', (mx, my), fontsize=7, color='#2ecc71', fontweight='bold',
                    ha='center', va='center', bbox=dict(boxstyle='round,pad=0.2', fc='white', alpha=0.8))

ax.set_xlabel('X = Radial depth (mm), 0=rim surface, negative=inward', fontsize=11)
ax.set_ylabel('Y = Half-width (mm), tangential', fontsize=11)
ax.set_title('Fir-Tree Slot 2D Profile: test_v18 LLM vs Correct Inclined Flanks', fontsize=13, fontweight='bold')
ax.axhline(y=0, color='gray', ls=':', alpha=0.4)
ax.axvline(x=0, color='gray', ls=':', alpha=0.4)
ax.legend(loc='lower left', fontsize=9)
ax.set_aspect('equal')
ax.grid(True, alpha=0.3)
ax.invert_xaxis()

# Annotations
ax.annotate('RIM SURFACE\n(mouth)', xy=(0, 4), fontsize=9, color='#e74c3c',
            xytext=(20, 15), textcoords='offset points', fontweight='bold',
            arrowprops=dict(arrowstyle='->', color='#e74c3c', lw=1.5))
ax.annotate('SLOT ROOT\n(20mm depth)', xy=(-20, 0), fontsize=9, color='#e74c3c',
            xytext=(-35, -20), textcoords='offset points', fontweight='bold',
            arrowprops=dict(arrowstyle='->', color='#e74c3c', lw=1.5))

# Segment type legend (use empty scatter plot trick to avoid format string parsing)
from matplotlib.lines import Line2D
custom_lines = [
    Line2D([0], [0], color='#e74c3c', lw=2, marker='s', ms=8, markerfacecolor='#e74c3c'),
    Line2D([0], [0], color='#e74c3c', lw=2, marker='^', ms=8, markerfacecolor='#e74c3c'),
    Line2D([0], [0], color='#2ecc71', lw=2, ls='--', marker='o', ms=8, markerfacecolor='#2ecc71'),
]
ax.legend(custom_lines, ['H: horizontal (dx!=0, dy=0)', 'V: vertical (dx=0, dy!=0)', 'I: inclined (both dx,dy !=0)'],
          loc='lower left', fontsize=9, title='LLM segments (24 total)')
# Remove the original legend call (it was already added with plot lines)

# Stats box
stats = f"LLM: 24 pts, {len(cutter_pts)//2}H + {len(cutter_pts)//2}V = 0 inclined\nIdeal: 18 pts, all lobes have inclined flanks"
ax.text(0.02, 0.02, stats, transform=ax.transAxes, fontsize=9, verticalalignment='bottom',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

# ── RIGHT: Disc R-Z profile ──
ax2 = axes[1]
dxs = [p[0] for p in disc_pts] + [disc_pts[0][0]]
dys = [p[1] for p in disc_pts] + [disc_pts[0][1]]
ax2.fill(dxs, dys, alpha=0.3, color='#3498db')
ax2.plot(dxs, dys, 'o-', color='#3498db', lw=2.5, ms=5)
for i, (x, y) in enumerate(disc_pts):
    ax2.annotate(str(i), (x, y), fontsize=7, color='#2980b9', xytext=(5, 5), textcoords='offset points')

ax2.annotate('BORE\nr=60', xy=(60, 0), fontsize=10, color='#e74c3c', fontweight='bold', ha='center')
ax2.annotate('HUB  r=60-120\nZ=+-38 (76mm)', xy=(90, 0), fontsize=8, color='#e74c3c', ha='center')
ax2.annotate('WEB  r=120-215\n44mm->30mm', xy=(167, 0), fontsize=8, color='#e67e22', ha='center')
ax2.annotate('RIM  r=215-250\nZ=+-30 (60mm)', xy=(232, 0), fontsize=8, color='#27ae60', ha='center')
ax2.annotate('FIR-TREE\nSLOTS x60', xy=(250, 0), fontsize=9, color='#e74c3c', fontweight='bold',
            xytext=(25, 25), textcoords='offset points',
            arrowprops=dict(arrowstyle='->', color='#e74c3c', lw=1.5))

ax2.set_xlabel('R = Radius (mm)', fontsize=11)
ax2.set_ylabel('Z = Axial (mm), revolve axis', fontsize=11)
ax2.set_title('Turbine Disc R-Z Cross-Section (XZ plane, 360 deg revolve)', fontsize=13, fontweight='bold')
ax2.axhline(y=0, color='gray', ls=':', alpha=0.4)
ax2.axvline(x=0, color='gray', ls=':', alpha=0.4)
ax2.set_aspect('equal')
ax2.grid(True, alpha=0.3)

plt.tight_layout()
out = 'E:/auto_detection_process/turbine_disc/test_v18_slots_half_cut/cutter_profile_analysis.png'
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='white')
print(f'Saved: {out}')
print(f'Size: {os.path.getsize(out)} bytes')
