"""一次性：渲染 D15 涡轮盘 STL 三维图（等距/俯视/侧视），供人工检查。

用法: .conda/python.exe _param_experiment/_render_d15_stl.py
产物: _param_experiment/output/d15_disc_render.png
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

_HERE = Path(__file__).resolve().parent
STL = (_HERE.parent / "app" / "text-to-cad" / "server" / "output"
       / "check_D15_v9" / "output.stl")
OUT = _HERE / "output" / "d15_v9_disc_render.png"


def load_stl(path: Path) -> np.ndarray:
    """解析二进制 STL（OCC 输出），返回 (N,3,3) 三角形顶点。"""
    with path.open("rb") as f:
        head = f.read(84)
        if head[80:84] == b"":  # ASCII 兜底（本项目为二进制）
            pass
        n = struct.unpack("<I", head[80:84])[0]
        buf = f.read(50 * n)
    dtype = np.dtype([("norm", "<f4", (3,)), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    rec = np.frombuffer(buf, dtype=dtype, count=n)
    return rec["v"].copy()


def draw(ax, tri, c=(0.62, 0.72, 0.86), alpha=1.0):
    pc = Poly3DCollection(tri, facecolor=c, alpha=alpha,
                          linewidths=0.0, edgecolors="none")
    ax.add_collection3d(pc)


def finalize(ax, tri, azim, elev, title):
    x0, x1 = tri[..., 0].min(), tri[..., 0].max()
    y0, y1 = tri[..., 1].min(), tri[..., 1].max()
    z0, z1 = tri[..., 2].min(), tri[..., 2].max()
    mid = np.array([(x0+x1)/2, (y0+y1)/2, (z0+z1)/2])
    span = max(x1-x0, y1-y0, z1-z0) / 2 * 1.08
    ax.set_xlim(mid[0]-span, mid[0]+span)
    ax.set_ylim(mid[1]-span, mid[1]+span)
    ax.set_zlim(mid[2]-span, mid[2]+span)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=elev, azim=azim)
    ax.set_title(title, fontsize=11)
    ax.set_axis_off()


def main():
    tri = load_stl(STL)
    print(f"STL faces: {len(tri)}")
    # 降采样保持渲染速度
    stride = 1
    if len(tri) > 150_000:
        stride = max(1, len(tri) // 120_000)
    ts = tri[::stride]
    print(f"render faces (stride={stride}): {len(ts)}")

    # 榫槽局部放大：扇区 ±22°、半径 200-255（轮缘榫槽区）
    cx, cy = tri[..., 0], tri[..., 1]
    r = np.sqrt(cx * cx + cy * cy)
    ang = np.degrees(np.arctan2(cy, cx))
    mask = (r.min(axis=1) > 200) & (r.max(axis=1) < 255) & (np.abs(ang).max(axis=1) < 22)
    loc = tri[mask]
    print(f"局部榫槽 faces: {len(loc)}")

    fig = plt.figure(figsize=(16, 5.0))
    views = [("等距视图 (3/4)", -58, 22), ("俯视图 (轴向，见榫槽周向分布)", 0, 90),
             ("侧视图 (径向，见盘体剖面轮廓)", 90, 0),
             ("榫槽局部放大 (扇区±22°, 见齿形)", -58, 22)]
    for i, (title, azim, elev) in enumerate(views, 1):
        ax = fig.add_subplot(1, 4, i, projection="3d")
        tgt = loc if i == 4 else ts
        draw(ax, tgt)
        finalize(ax, tgt, azim, elev, title)
    fig.suptitle("D15 涡轮盘 v9 (od=500 teeth=2 slots=40 depth=21.2 throat=8)  —  slot2d 自然结构  ",
                 fontsize=13, y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("渲染产物:", OUT)


if __name__ == "__main__":
    sys.exit(main())
