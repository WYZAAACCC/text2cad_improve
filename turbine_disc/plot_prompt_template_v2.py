"""Plot corrected fir-tree template with proper neck flats"""
import os
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

# CORRECTED template: neck flat before each flare-out
pts = [
    # RIGHT half (clockwise, mouth->root, Y>=0)
    (0.0, 4.0),      # 0: mouth top
    (-3.0, 2.5),     # 1: wedge entrance (inclined IN)
    (-4.0, 7.5),     # 2: first lobe flank OUT (inclined)
    (-7.0, 7.5),     # 3: first lobe flat top (horizontal, 3mm)
    (-9.0, 2.0),     # 4: first lobe slope back IN to wedge
    (-10.0, 2.0),    # 5: first NECK flat (along wedge, short)
    (-10.5, 6.5),    # 6: second lobe flank OUT from neck (inclined)
    (-13.0, 6.5),    # 7: second lobe flat top (horizontal, 2.5mm)
    (-15.0, 1.5),    # 8: second lobe slope back IN to wedge
    (-16.0, 1.5),    # 9: second NECK flat (along wedge)
    (-18.0, 1.5),    # 10: root approach (along wedge)
    (-20.0, 1.5),    # 11: ROOT BOTTOM

    # LEFT half (root->mouth, Y<=0, mirrors right)
    (-20.0, -1.5),   # 12: cross to left
    (-18.0, -1.5),   # 13: root approach left
    (-16.0, -1.5),   # 14: second neck flat left (along wedge)
    (-15.0, -1.5),   # 15: second lobe slope (left side is mirrored)
    (-13.0, -6.5),   # 16: second lobe top left (horizontal)
    (-10.5, -6.5),   # 17: second lobe slope IN toward neck
    (-10.0, -2.0),   # 18: first NECK flat left (along wedge)
    (-9.0, -2.0),    # 19: first lobe slope (left mirror)
    (-7.0, -7.5),    # 20: first lobe top left (horizontal)
    (-4.0, -7.5),    # 21: first lobe slope IN toward wedge
    (-3.0, -2.5),    # 22: wedge entrance left
    (0.0, -4.0),     # 23: MOUTH BOTTOM
]

fig, ax = plt.subplots(1, 1, figsize=(13, 10))
fig.patch.set_facecolor('white')

# Draw segments
for i in range(len(pts)):
    j = (i+1) % len(pts)
    dx, dy = pts[j][0]-pts[i][0], pts[j][1]-pts[i][1]
    if abs(dy) < 0.01:
        color, lw, label = '#e74c3c', 3.0, 'Tooth top / neck flat (horizontal)'
    elif abs(dx) < 0.01:
        color, lw, label = '#f39c12', 3.0, 'Vertical crossing'
    else:
        color, lw, label = '#27ae60', 3.5, 'Inclined flank'
    ax.plot([pts[i][0], pts[j][0]], [pts[i][1], pts[j][1]], '-', color=color, lw=lw, alpha=0.9, zorder=3)

# Label vertices
for i, (x, y) in enumerate(pts):
    ay = abs(y)
    if i in [0, 23]: vc, vs, vm = '#e74c3c', 100, 's'          # mouth
    elif i in [11, 12]: vc, vs, vm = '#8e44ad', 90, 'D'        # root
    elif ay > 6: vc, vs, vm = '#27ae60', 90, '^'               # lobe peak
    elif ay < 2.1 and i in [5, 9, 14, 18]: vc, vs, vm = '#e67e22', 80, 'h'  # neck flat
    elif ay < 2.6: vc, vs, vm = '#9b59b6', 70, 'o'             # wedge
    else: vc, vs, vm = '#2c3e50', 50, 'o'
    ax.plot(x, y, vm, color=vc, ms=9, zorder=5, markeredgewidth=1.5,
           markeredgecolor='white' if vc!='#2c3e50' else vc)
    ax.annotate(str(i), (x,y), fontsize=6.5, fontweight='bold', color=vc, xytext=(6,6), textcoords='offset points', zorder=10)

# Wedge envelope
wedge_r = [(0,2.5), (-3,2.5), (-10,2.0), (-16,1.5), (-20,1.5)]
wedge_l = [(0,-2.5), (-3,-2.5), (-10,-2.0), (-16,-1.5), (-20,-1.5)]
ax.plot([p[0] for p in wedge_r], [p[1] for p in wedge_r], '--', color='#9b59b6', lw=2, alpha=0.6)
ax.plot([p[0] for p in wedge_l], [p[1] for p in wedge_l], '--', color='#9b59b6', lw=2, alpha=0.6)

# HIGHLIGHT the neck flats
for idx, name in [(5, 'NECK flat R'), (9, 'NECK flat R2'), (18, 'NECK flat L'), (14, 'NECK flat L2')]:
    x, y = pts[idx]
    ax.annotate(name, (x, y), fontsize=8, color='#e67e22', fontweight='bold',
                xytext=(0, -20 if y>0 else 20), textcoords='offset points', ha='center',
                arrowprops=dict(arrowstyle='->', color='#e67e22', lw=1.5))

# Segment [4]->[5] highlight (the neck flat)
ax.annotate('', xy=(-9, 2.0), xytext=(-10, 2.0),
            arrowprops=dict(arrowstyle='<->', color='#e67e22', lw=3))
ax.annotate('neck flat\n(along wedge)', xy=(-9.5, 2.8), fontsize=8, color='#e67e22',
            ha='center', fontweight='bold')

# [5]->[6] highlight (flare out)
ax.annotate('flare OUT\nto 2nd lobe', xy=(-10.25, 4.25), fontsize=8, color='#27ae60',
            ha='center', fontweight='bold',
            arrowprops=dict(arrowstyle='->', color='#27ae60', lw=1.5))

# Annotations
ax.annotate('MOUTH (4mm)', xy=(0,4), fontsize=10, fontweight='bold', color='#e74c3c',
            ha='left', xytext=(25,0), textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.3', fc='#fdedec', ec='#e74c3c'),
            arrowprops=dict(arrowstyle='->', color='#e74c3c', lw=2))
ax.annotate('1st TOOTH\nY=7.5mm', xy=(-5.5,7.5), fontsize=10, fontweight='bold', color='#27ae60',
            ha='center', xytext=(0,25), textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.3', fc='#e8f8f5', ec='#27ae60'),
            arrowprops=dict(arrowstyle='->', color='#27ae60', lw=2))
ax.annotate('2nd TOOTH\nY=6.5mm', xy=(-12,6.5), fontsize=10, fontweight='bold', color='#e67e22',
            ha='center', xytext=(0,25), textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.3', fc='#fef5e7', ec='#e67e22'),
            arrowprops=dict(arrowstyle='->', color='#e67e22', lw=2))
ax.annotate('ROOT\nY=1.5mm', xy=(-20,1.5), fontsize=9, fontweight='bold', color='#8e44ad',
            ha='right', xytext=(-15,-25), textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.3', fc='#f4ecf7', ec='#8e44ad'),
            arrowprops=dict(arrowstyle='->', color='#8e44ad', lw=2))

params = (
    'CORRECTED TEMPLATE (with neck flats)\n'
    '=====================================\n'
    '24 points (12 R + 12 L)\n'
    'First neck flat: [4]->[5] @ Y=2.0\n'
    'Second neck flat: [8]->[9] @ Y=1.5\n'
    '1st lobe Ymax = 7.5mm\n'
    '2nd lobe Ymax = 6.5mm\n'
    'Wedge |Y|: 2.5 > 2.0 > 1.5\n'
    'Fillet: R=1.5mm, at_vertex_index\n'
    '  = [1,2,3,4,6,7,8,10, 13,15,16,17,19,20,21,22]'
)
ax.text(0.02, 0.98, params, transform=ax.transAxes, fontsize=8.5, verticalalignment='top',
        fontfamily='monospace', bbox=dict(boxstyle='round', fc='#2c3e50', alpha=0.07, ec='#2c3e50', pad=0.8))

leg = [Line2D([0],[0], color='#27ae60', lw=3.5, label='Inclined flank'),
       Line2D([0],[0], color='#e74c3c', lw=3, label='Tooth top / neck flat (H)'),
       Line2D([0],[0], color='#f39c12', lw=3, label='Vertical crossing'),
       Line2D([0],[0], color='#9b59b6', lw=2, ls='--', label='Wedge envelope'),
       Line2D([0],[0], color='#e67e22', lw=0, marker='h', ms=10, label='Neck flat point')]
ax.legend(handles=leg, loc='lower right', fontsize=8, framealpha=0.9)

ax.set_xlabel('X = Radial depth (mm), 0=rim surface, negative=toward center', fontsize=11, fontweight='bold')
ax.set_ylabel('Y = Tangential half-width (mm), symmetric about Y=0', fontsize=11, fontweight='bold')
ax.set_title('Corrected Fir-Tree Slot Template\n(24 points, neck flats between teeth, progressively narrowing inward)',
             fontsize=14, fontweight='bold', pad=15)
ax.axhline(y=0, color='#7f8c8d', ls='-', alpha=0.4)
ax.axvline(x=0, color='#7f8c8d', ls='-', alpha=0.4)
ax.set_aspect('equal'); ax.grid(True, alpha=0.15); ax.invert_xaxis()

plt.tight_layout()
out = 'E:/auto_detection_process/turbine_disc/prompt_firtree_template_v2.png'
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='white')
print(f'Saved: {out} ({os.path.getsize(out)} bytes)')
