"""Plot v3 fir-tree template — longer neck flats + bottom tooth"""
import os
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

pts = [
    # RIGHT half (clockwise mouth->root, Y>=0) — 12 points
    (0.0, 4.0),      # 0: mouth top
    (-3.0, 2.5),     # 1: wedge entrance (inclined IN)
    (-4.0, 7.5),     # 2: 1st lobe flank OUT (inclined, ~26 deg)
    (-7.0, 7.5),     # 3: 1st lobe flat top (H, 3mm)
    (-9.0, 2.5),     # 4: slope back IN to wedge (inclined)
    (-12.0, 2.5),    # 5: NECK 1 flat — 3mm along wedge ← room for fillet!
    (-12.5, 6.5),    # 6: 2nd lobe flank OUT (inclined)
    (-14.5, 6.5),    # 7: 2nd lobe flat top (H, 2mm)
    (-16.0, 2.0),    # 8: slope back IN to wedge (inclined)
    (-18.0, 2.0),    # 9: NECK 2 flat — 2mm along wedge
    (-18.5, 3.5),    # 10: BOTTOM TOOTH flare OUT (small 3rd tooth)
    (-20.0, 3.0),    # 11: ROOT (rounded bottom tooth tip)

    # LEFT half (root->mouth, Y<=0) — 12 points, mirror
    (-20.0, -3.0),   # 12: cross to left
    (-18.5, -3.5),   # 13: bottom tooth left
    (-18.0, -2.0),   # 14: neck 2 left
    (-16.0, -2.0),   # 15: slope left
    (-14.5, -6.5),   # 16: 2nd lobe top left
    (-12.5, -6.5),   # 17: 2nd lobe flank IN left
    (-12.0, -2.5),   # 18: NECK 1 flat left
    (-9.0, -2.5),    # 19: slope left
    (-7.0, -7.5),    # 20: 1st lobe top left
    (-4.0, -7.5),    # 21: 1st lobe flank IN left
    (-3.0, -2.5),    # 22: wedge entrance left
    (0.0, -4.0),     # 23: MOUTH BOTTOM
]

fig, ax = plt.subplots(1, 1, figsize=(13, 10))
fig.patch.set_facecolor('white')

# Draw segments
for i in range(len(pts)):
    j = (i+1) % len(pts)
    dx, dy = pts[j][0]-pts[i][0], pts[j][1]-pts[i][1]
    if abs(dy) < 0.01: color, lw = '#e74c3c', 3.0        # H
    elif abs(dx) < 0.01: color, lw = '#f39c12', 3.0       # V
    else: color, lw = '#27ae60', 3.5                       # Inclined
    ax.plot([pts[i][0], pts[j][0]], [pts[i][1], pts[j][1]], '-', color=color, lw=lw, alpha=0.9, zorder=3)

# Label vertices
for i, (x, y) in enumerate(pts):
    ay = abs(y)
    if i in [0, 23]:   c, s, m = '#e74c3c', 110, 's'       # mouth
    elif i in [11, 12]: c, s, m = '#8e44ad', 100, 'D'       # root
    elif i in [10, 13]: c, s, m = '#e67e22', 80, 'p'        # bottom tooth
    elif ay > 6.4:      c, s, m = '#27ae60', 90, '^'        # lobe peak
    elif ay < 2.1 and i in [5, 9, 14, 18]: c, s, m = '#e67e22', 85, 'h'  # neck flat
    elif ay < 2.6:      c, s, m = '#9b59b6', 70, 'o'        # wedge
    else:               c, s, m = '#2c3e50', 50, 'o'
    ax.plot(x, y, m, color=c, ms=9, zorder=5, markeredgewidth=1.5,
           markeredgecolor='white' if c!='#2c3e50' else c)
    ax.annotate(str(i), (x,y), fontsize=6.5, fontweight='bold', color=c,
                xytext=(6,6), textcoords='offset points', zorder=10)

# Wedge envelope
wr = [(0,2.5),(-3,2.5),(-12,2.5),(-18,2.0),(-20,2.0)]
wl = [(0,-2.5),(-3,-2.5),(-12,-2.5),(-18,-2.0),(-20,-2.0)]
ax.plot([p[0] for p in wr], [p[1] for p in wr], '--', color='#9b59b6', lw=2, alpha=0.5)
ax.plot([p[0] for p in wl], [p[1] for p in wl], '--', color='#9b59b6', lw=2, alpha=0.5)

# ---- Annotations ----

# Neck flats (highlight the 3mm flat)
for seg, label in [((4,5), 'NECK 1: 3mm flat'), ((8,9), 'NECK 2: 2mm flat')]:
    i1, i2 = seg
    mx, my = (pts[i1][0]+pts[i2][0])/2, (pts[i1][1]+pts[i2][1])/2
    ax.plot([pts[i1][0], pts[i2][0]], [pts[i1][1], pts[i2][1]], '-', color='#e67e22', lw=6, alpha=0.4, zorder=2)
    ax.annotate(label, (mx, my), fontsize=9, color='#e67e22', fontweight='bold', ha='center',
                xytext=(0, 18 if my>0 else -18), textcoords='offset points',
                arrowprops=dict(arrowstyle='->', color='#e67e22', lw=2))

# Bottom tooth annotation
ax.annotate('BOTTOM TOOTH\n(3rd small lobe)\nYmax=3.5mm', xy=(-19.25, 3.25), fontsize=9,
            fontweight='bold', color='#e67e22', ha='center', xytext=(15, 15),
            textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.3', fc='#fef5e7', ec='#e67e22', alpha=0.9),
            arrowprops=dict(arrowstyle='->', color='#e67e22', lw=2))

# Lobe annotations
ax.annotate('1st TOOTH PAIR\nYmax=7.5mm (WIDEST)', xy=(-5.5,7.5), fontsize=10, fontweight='bold',
            color='#27ae60', ha='center', xytext=(0,28), textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.3', fc='#e8f8f5', ec='#27ae60', alpha=0.9),
            arrowprops=dict(arrowstyle='->', color='#27ae60', lw=2))
ax.annotate('2nd TOOTH PAIR\nYmax=6.5mm (NARROWER)', xy=(-13.5,6.5), fontsize=10, fontweight='bold',
            color='#2980b9', ha='center', xytext=(0,28), textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.3', fc='#ebf5fb', ec='#2980b9', alpha=0.9),
            arrowprops=dict(arrowstyle='->', color='#2980b9', lw=2))
ax.annotate('MOUTH\nhalf-width 4mm', xy=(0,4), fontsize=10, fontweight='bold', color='#e74c3c',
            ha='left', xytext=(25,0), textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.3', fc='#fdedec', ec='#e74c3c', alpha=0.9),
            arrowprops=dict(arrowstyle='->', color='#e74c3c', lw=2))

# RIM SURFACE line
ax.axvline(x=0, color='#34495e', ls='-', lw=3, alpha=0.6, zorder=1)
ax.annotate('RIM SURFACE (X=0, R=250mm)', xy=(0, -8.5), fontsize=10, fontweight='bold',
            color='#34495e', ha='center', rotation=90)

# Stats box
stats = (
    'TEMPLATE v3 — 24 points (12R + 12L)\n'
    '=====================================\n'
    '1st lobe  Ymax = 7.5mm (widest)\n'
    '2nd lobe  Ymax = 6.5mm (narrower)\n'
    'Btm tooth Ymax = 3.5mm (narrowest)\n'
    'Wedge |Y|: 2.5 > 2.5 > 2.0 > 2.0\n'
    'NECK 1 flat: 3mm (X=-9 to -12)\n'
    'NECK 2 flat: 2mm (X=-16 to -18)\n'
    'Depth: 20mm (X=0 to X=-20)\n'
    'Fillet: R=1.5mm at all interiors\n'
    '   at_vertex_index = [1..10, 13..22]\n'
)
ax.text(0.02, 0.98, stats, transform=ax.transAxes, fontsize=8.5, verticalalignment='top',
        fontfamily='monospace', bbox=dict(boxstyle='round', fc='#2c3e50', alpha=0.07, ec='#2c3e50', pad=0.8))

leg = [Line2D([0],[0], color='#27ae60', lw=3.5, label='Inclined flank'),
       Line2D([0],[0], color='#e74c3c', lw=3, label='Tooth top / neck flat (H)'),
       Line2D([0],[0], color='#f39c12', lw=3, label='Vertical crossing'),
       Line2D([0],[0], color='#9b59b6', lw=2, ls='--', label='Wedge envelope'),
       Line2D([0],[0], color='#e67e22', lw=6, alpha=0.4, label='Neck flat highlight')]
ax.legend(handles=leg, loc='lower right', fontsize=8, framealpha=0.9)

ax.set_xlabel('X = Radial depth (mm)    0=rim surface, negative=toward disc center', fontsize=11, fontweight='bold')
ax.set_ylabel('Y = Tangential half-width (mm)    symmetric about Y=0', fontsize=11, fontweight='bold')
ax.set_title('Fir-Tree Slot Template v3\n(24 points, 3mm neck flats for fillets, bottom tooth at root)',
             fontsize=14, fontweight='bold', pad=15)
ax.axhline(y=0, color='#7f8c8d', ls='-', alpha=0.3)
ax.set_aspect('equal'); ax.grid(True, alpha=0.15); ax.invert_xaxis()

plt.tight_layout()
out = 'E:/auto_detection_process/turbine_disc/prompt_firtree_template_v3.png'
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='white')
print(f'Saved: {out} ({os.path.getsize(out)} bytes)')
