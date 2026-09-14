"""Render coarse STEP tessellation views for visual inspection only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")

import cadquery as cq  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    shape = cq.importers.importStep(str(args.step)).val()
    vertices, triangles = shape.tessellate(2.0)
    points = np.array([[v.x, v.y, v.z] for v in vertices])
    faces = np.array(triangles)

    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    for triangles_idx, values, x_idx, y_idx, title, ax in (
        (faces, points, 0, 1, "XY", axes[0]),
        (faces, points, 0, 2, "XZ", axes[1]),
    ):
        from matplotlib.collections import PolyCollection

        polys = values[triangles_idx][:, :, (x_idx, y_idx)]
        collection = PolyCollection(
            polys, facecolors="none", edgecolors="0.2", linewidths=0.05
        )
        ax.add_collection(collection)
        ax.autoscale()
        ax.set_aspect("equal")
        ax.set_title(title)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=160, bbox_inches="tight")
    print(args.output)


if __name__ == "__main__":
    main()
