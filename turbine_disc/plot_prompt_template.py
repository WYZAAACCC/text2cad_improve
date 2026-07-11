"""Plot the exact fir-tree template from the prompt"""
import os
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

pts = [
    (0.0, 4.0),     (-3.0, 2.5),    (-4.0, 7.5),    (-7.0, 7.5),
    (-9.0, 2.0),    (-10.0, 6.5),   (-13.0, 6.5),   (-15.0, 1.5),
    (-18.0, 1.5),   (-20.0, 1.5),   (-20.0, -1.5),  (-18.0, -1.5),
    (-15.0, -1.5),  (-13.0, -6.5),  (-10.0, -6.5),  (-9.0, -2.0),
    (-7.0, -7.5),   (-4.0, -7.5),   (-3.0, -2.5),   (0.0, -4.0),
]

fig, ax = plt.subplots(1, 1, figsize=(12, 10))
fig.patch.set_facecolor('white')

# Draw segments by type
for i in range(len(pts)):
    j = (i+1) % len(pts)
    dx, dy = pts[j][0]-pts[i][0], pts[j][1]-pts[i][1]
    if abs(dy) < 0.01: color, lw = '#e74c3c', 3.0
    elif abs(dx) < 0.01: color, lw = '#f39c12', 3.0
    else: color, lw = '#27ae60', 3.5
    ax.plot([pts[i][0], pts[j][0]], [pts[i][1], pts[j][1]], '-', color=color, lw=lw, alpha=0.9, zorder=3)

# Vertices
for i, (x, y) in enumerate(pts):
    ay = abs(y)
    if i in [0, 19]: vc, vs, vm = '#e74c3c', 90, 's'
    elif i in [9, 10]: vc, vs, vm = '#8e44ad', 80, 'D'
    elif ay > 6: vc, vs, vm = '#27ae60', 80, '^'
    elif ay < 2.6 and i not in [0,19]: vc, vs, vm = '#9b59b6', 70, 'o'
    else: vc, vs, vm = '#2c3e50', 50, 'o'
    ax.plot(x, y, vm, color=vc, ms=8, zorder=5, markeredgewidth=1.5, markeredgecolor='white' if vc!='#2c3e50' else vc)
    ax.annotate(str(i), (x,y), fontsize=7, fontweight='bold', color=vc, xytext=(6,6), textcoords='offset points', zorder=10)

# Wedge envelope
w_r = [(0,2.5),(-3,2.5),(-9,2.0),(-15,1.5),(-20,1.5)]
w_l = [(0,-2.5),(-3,-2.5),(-9,-2.0),(-15,-1.5),(-20,-1.5)]
ax.plot([p[0] for p in w_r], [p[1] for p in w_r], '--', color='#9b59b6', lw=2, alpha=0.7, label='Wedge envelope')
ax.plot([p[0] for p in w_l], [p[1] for p in w_l], '--', color='#9b59b6', lw=2, alpha=0.7)

# Annotations
ax.annotate('MOUTH\nhalf-width 4mm', xy=(0,4), fontsize=10, fontweight='bold', color='#e74c3c',
            ha='left', xytext=(20,0), textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.3', fc='#fdedec', ec='#e74c3c', alpha=0.9),
            arrowprops=dict(arrowstyle='->', color='#e74c3c', lw=2))

ax.annotate('1st TOOTH PAIR\nYmax=7.5mm (WIDEST)', xy=(-5.5,7.5), fontsize=10, fontweight='bold', color='#27ae60',
            ha='center', xytext=(0,25), textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.3', fc='#e8f8f5', ec='#27ae60', alpha=0.9),
            arrowprops=dict(arrowstyle='->', color='#27ae60', lw=2))

ax.annotate('2nd TOOTH PAIR\nYmax=6.5mm (NARROWER)', xy=(-11.5,6.5), fontsize=10, fontweight='bold', color='#e67e22',
            ha='center', xytext=(0,25), textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.3', fc='#fef5e7', ec='#e67e22', alpha=0.9),
            arrowprops=dict(arrowstyle='->', color='#e67e22', lw=2))

ax.annotate('ROOT\nY=1.5mm\ndepth=20mm', xy=(-20,1.5), fontsize=9, fontweight='bold', color='#8e44ad',
            ha='right', xytext=(-15,-25), textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.3', fc='#f4ecf7', ec='#8e44ad', alpha=0.9),
            arrowprops=dict(arrowstyle='->', color='#8e44ad', lw=2))

ax.annotate('RIM SURFACE\nX=0, R=250mm', xy=(0,0), fontsize=10, fontweight='bold', color='#34495e',
            ha='right', xytext=(-20,-30), textcoords='offset points',
            arrowprops=dict(arrowstyle='->', color='#34495e', lw=2))

# Params
params = (
    'PARAMETERS (KT787-JB-215 based)\n'
    '================================\n'
    'Wedge half-angle: ~7 deg\n'
    'Tooth pairs: 2\n'
    'Mouth half-width: 4.0mm\n'
    '1st lobe Ymax: 7.5mm\n'
    '2nd lobe Ymax: 6.5mm\n'
    'Neck wedge |Y|: 2.5 > 2.0 > 1.5\n'
    'Root half-width: 1.5mm\n'
    'Depth: 20mm (0 to -20)\n'
    'Points: 20 (10R + 10L)\n'
    'Fillet: R=1.5mm at all interiors\n'
    'Tooth top: 3mm flat (H segments)\n'
    'Flank: |dy/dx| = 1.7~5.0'
)
ax.text(0.02, 0.98, params, transform=ax.transAxes, fontsize=8.5, verticalalignment='top',
        fontfamily='monospace', bbox=dict(boxstyle='round', fc='#2c3e50', alpha=0.07, ec='#2c3e50', pad=0.8))

# Legend
from matplotlib.lines import Line2D
leg = [Line2D([0],[0], color='#27ae60', lw=3.5, label='Inclined flank (dx!=0, dy!=0)'),
       Line2D([0],[0], color='#e74c3c', lw=3, label='Horizontal tooth top (dy=0)'),
       Line2D([0],[0], color='#f39c12', lw=3, label='Vertical crossing (dx=0)'),
       Line2D([0],[0], color='#9b59b6', lw=2, ls='--', label='Wedge envelope')]
ax.legend(handles=leg, loc='lower right', fontsize=8, framealpha=0.9)

ax.set_xlabel('X = Radial depth (mm)  0=rim surface, negative=toward disc center', fontsize=11, fontweight='bold')
ax.set_ylabel('Y = Tangential half-width (mm)  symmetric about Y=0', fontsize=11, fontweight='bold')
ax.set_title('Prompt Template: Fir-Tree Slot 2D Profile\n(2 tooth pairs, wedge-shaped, progressively narrowing inward)',
             fontsize=14, fontweight='bold', pad=15)
ax.axhline(y=0, color='#7f8c8d', ls='-', alpha=0.4)
ax.axvline(x=0, color='#7f8c8d', ls='-', alpha=0.4)
ax.set_aspect('equal')
ax.grid(True, alpha=0.15)
ax.invert_xaxis()

plt.tight_layout()
out = 'E:/auto_detection_process/turbine_disc/prompt_firtree_template.png'
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='white')
print(f'Saved: {out} ({os.path.getsize(out)} bytes)')
