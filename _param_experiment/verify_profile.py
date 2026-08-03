"""验证完整参数化轮廓：轴对称性 + ASCII 图。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fir_tree_parametric import FirTreeParams, generate_profile


def ascii_plot(pts, title):
    xs = [pt['x_mm'] for pt in pts]
    ys = [pt['y_mm'] for pt in pts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    xr = (xmax - xmin) or 1
    yr = (ymax - ymin) or 1
    W, H = 72, 20
    grid = [[' '] * W for _ in range(H)]
    mid = H - 1 - int((0 - ymin) / yr * (H - 1))
    for gx in range(W):
        if 0 <= mid < H:
            grid[mid][gx] = '-'
    for i, pt in enumerate(pts):
        gx = int((pt['x_mm'] - xmin) / xr * (W - 1))
        gy = H - 1 - int((pt['y_mm'] - ymin) / yr * (H - 1))
        grid[gy][gx] = str(i)[-1]
    print(f'=== {title} (0=口部上, 末=口部下, 横线=y=0中心线) ===')
    for ri, row in enumerate(grid):
        print('  %2d %s' % (ri, ''.join(row)))
    print('  x: %.1f~%.1f  y: %.1f~%.1f' % (xmin, xmax, ymin, ymax))


def main():
    p = FirTreeParams(
        teeth_count=3, slot_depth_mm=24,
        tooth_height_mm=[4, 3, 2], tooth_thickness_mm=[2, 2, 2],
        top_flank_angle_deg=[45, 45, 45], under_flank_angle_deg=[40, 40, 40],
        neck_half_width_mm=[2, 2.2, 2.5, 3], neck_platform_mm=1.0,
    )
    pts = generate_profile(p)
    N = len(pts)
    print('总点数=%d (每侧=%d)' % (N, N // 2))
    print()
    for i, pt in enumerate(pts):
        print('  [%2d] (%8.3f, %8.3f)' % (i, pt['x_mm'], pt['y_mm']))
    print()
    ascii_plot(pts, 'S1 三齿 完整轮廓')
    print()
    # 轴对称检查
    ok = True
    for i in range(N // 2):
        a, b = pts[i], pts[N - 1 - i]
        if abs(a['x_mm'] - b['x_mm']) > 1e-6 or abs(a['y_mm'] + b['y_mm']) > 1e-6:
            ok = False
            print('[不对称] [%d](%s) vs [%d](%s)' % (i, a, N - 1 - i, b))
    print('轴对称(关于 y=0):', 'PASS' if ok else 'FAIL')


if __name__ == '__main__':
    main()
