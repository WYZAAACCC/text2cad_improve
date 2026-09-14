"""Draw the sector so the two candidate selections can be looked at.

Everything about this question has been numbers so far, and the numbers say
two sets of faces are the same kind of thing: planar, facing the axis,
mirrored pairs, at different radii and from different origins. That is not a
thing to decide from a table.

The part is prismatic in z - every face in question stands parallel to the
axis - so a view down the axis draws each flank as a line and the slot as the
zigzag it is. That is the projection worth looking at; a shaded 3D view of a
300 mm disc at this scale shows a grey slab and nothing else.

    python render_selection.py [output.png]
"""
from __future__ import annotations

import pathlib
import sys
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))

from seekflow_structural.tools import geometry  # noqa: E402

BUNDLE = REPO / "_cfd_experiment" / "input" / "lineage" / "D27"
THETA_LOW, THETA_HIGH = 9.0, 27.0

# Cut by the pattern cutters, at the rim. What the agent selected today, and
# what D19's cross-revision-verified answer looks like.
AGENT_FACES = [
    3954, 3962, 3970, 3978, 3990, 3998, 4006, 4014,
    4020, 4028, 4036, 4044, 4056, 4064, 4072, 4080,
    4086, 4094, 4102, 4110, 4122, 4130, 4138, 4146,
]
# Carried from the disc, mid-web. What the earlier pipeline selected.
REFERENCE_FACES = [9, 10, 11, 12, 13, 15]

GREY = "#9aa3ad"
AGENT = "#c0392b"
REFERENCE = "#1f5fa8"


def projected_edges(face, deflection: float = 0.6):
    """A face's triangle edges, projected down the axis.

    A flank stands parallel to the axis, so its projection is a segment; a
    face that turns to face along the axis projects to an area. Both draw as
    edges here, which is what makes the slot profile legible.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopLoc import TopLoc_Location

    BRepMesh_IncrementalMesh(face, deflection, False, 0.5, True)
    location = TopLoc_Location()
    triangulation = BRep_Tool.Triangulation_s(face, location)
    if triangulation is None:
        return []
    transform = location.Transformation()
    points = []
    for index in range(1, triangulation.NbNodes() + 1):
        node = triangulation.Node(index)
        node.Transform(transform)
        points.append((node.X(), node.Y()))
    points = np.asarray(points)
    segments = []
    for index in range(1, triangulation.NbTriangles() + 1):
        a, b, c = triangulation.Triangle(index).Get()
        for first, second in ((a, b), (b, c), (c, a)):
            segments.append([points[first - 1], points[second - 1]])
    return segments


def collect(session, indices, deflection: float = 0.6):
    faces = geometry.faces_of(session, "n_final_cut", 0)
    segments = []
    for index in indices:
        segments.extend(projected_edges(faces[index], deflection))
    return segments


def draw(ax, segments, color, width, *, alpha=1.0, zorder=2):
    if segments:
        ax.add_collection(LineCollection(
            segments, colors=color, linewidths=width, alpha=alpha,
            zorder=zorder,
        ))


def window(ax, centre_r, centre_theta, half_r, half_theta, title, subtitle):
    """A window in the (r, theta) plane, drawn as (x, y)."""
    theta = np.radians(np.linspace(centre_theta - half_theta,
                                   centre_theta + half_theta, 7))
    for radius, style in ((centre_r - half_r, ":"), (centre_r + half_r, ":")):
        ax.plot(radius * np.cos(theta), radius * np.sin(theta),
                style, color="#c6ccd4", linewidth=0.8, zorder=0)
    ax.set_aspect("equal")
    ax.set_title(f"{title}\n{subtitle}", fontsize=10)
    ax.set_xticks([]); ax.set_yticks([])
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_color("#d5dbe2")


def collect3d(session, indices, deflection=1.2):
    """Triangles in space, for a shaded view."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location

    faces = geometry.faces_of(session, "n_final_cut", 0)
    out = []
    for index in indices:
        face = faces[index]
        BRepMesh_IncrementalMesh(face, deflection, False, 0.5, True)
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is None:
            continue
        transform = location.Transformation()
        points = []
        for node_index in range(1, triangulation.NbNodes() + 1):
            node = triangulation.Node(node_index)
            node.Transform(transform)
            points.append((node.X(), node.Y(), node.Z()))
        points = np.asarray(points)
        flipped = face.Orientation() == TopAbs_REVERSED
        for tri_index in range(1, triangulation.NbTriangles() + 1):
            a, b, c = triangulation.Triangle(tri_index).Get()
            if flipped:
                a, c = c, a
            out.append(points[[a - 1, b - 1, c - 1]])
    return out


def add3d(ax, triangles, color, *, alpha=1.0):
    if triangles:
        ax.add_collection3d(Poly3DCollection(
            triangles, facecolor=color, edgecolor="none", alpha=alpha,
        ))
    points = np.concatenate(triangles) if triangles else None
    if points is not None:
        for setter, values in (
            (ax.set_xlim, points[:, 0]), (ax.set_ylim, points[:, 1]),
            (ax.set_zlim, points[:, 2]),
        ):
            setter(values.min(), values.max())


def main() -> int:
    out_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else (
        REPO / "_structural_experiment" / "output" / "D27_selection_3d.png"
    )
    session = geometry.open_bundle(BUNDLE)
    try:
        rows = geometry.face_rows(session, "n_final_cut", 0)
        sector = [
            index for index, row in enumerate(rows)
            if THETA_LOW <= row["centroid_cyl_mm_deg"][1] <= THETA_HIGH
        ]
        print(f"sector {THETA_LOW}-{THETA_HIGH} deg: {len(sector)} faces")
        print("  types:", dict(Counter(rows[i]["surface_type"] for i in sector)))

        marked = set(AGENT_FACES) | set(REFERENCE_FACES)
        rest = [i for i in sector if i not in marked]
        rim = [i for i in sector if rows[i]["centroid_cyl_mm_deg"][0] >= 265]
        mid = [i for i in sector if 195 <= rows[i]["centroid_cyl_mm_deg"][0] <= 230]

        # Three projections. A shaded 3D view was tried and abandoned: at
        # this scale, with matplotlib's painter's-algorithm depth sorting, a
        # 300 mm disc renders as a grey slab. Down the axis everything in
        # question is legible, because every face here stands parallel to the
        # axis and so draws as a line.
        fig, axes = plt.subplots(1, 3, figsize=(17, 6.4))
        fig.suptitle(
            "D27, one 18 deg sector (9-27 deg), viewed down the axis   |   "
            "red = selected today (four mirrored flank pairs cut by the "
            "pattern cutters)   blue = the earlier pipeline's selection "
            "(carried from the disc)",
            fontsize=11.5,
        )

        # 1. the whole sector. Limits set explicitly: a LineCollection does
        # not move the data limits, so autoscaling leaves the axes empty.
        draw(axes[0], collect(session, rest, 4.0), GREY, 0.35, alpha=0.7)
        draw(axes[0], collect(session, rim, 4.0), "#6f7883", 0.5, alpha=0.95)
        draw(axes[0], collect(session, REFERENCE_FACES), REFERENCE, 2.2)
        draw(axes[0], collect(session, AGENT_FACES), AGENT, 2.2)
        for boundary in (THETA_LOW, THETA_HIGH):
            angle = np.radians(boundary)
            axes[0].plot([60 * np.cos(angle), 302 * np.cos(angle)],
                         [60 * np.sin(angle), 302 * np.sin(angle)],
                         ":", color="#c6ccd4", linewidth=0.9, zorder=0)
        axes[0].set_xlim(20, 312)
        axes[0].set_ylim(-5, 152)
        axes[0].set_aspect("equal")
        axes[0].set_title(
            "the whole sector, r 60 to 300\nboth selections are a few "
            "millimetres across at this scale", fontsize=10,
        )
        axes[0].set_xticks([]); axes[0].set_yticks([])

        # 2. one rim slot, which is where the agent's faces are
        draw(axes[1], collect(session, [i for i in rim if i not in marked], 0.5),
             GREY, 0.9, alpha=0.9)
        draw(axes[1], collect(session, [i for i in AGENT_FACES
                                        if i in set(rim)] or AGENT_FACES, 0.5),
             AGENT, 2.0)
        window(axes[1], 288, 18, 22, 5.5,
               "the rim: a fir-tree slot",
               "red = today's selection, 4 mirrored pairs, r 280.7-295.4")

        # 3. the mid-web band the earlier pipeline used
        draw(axes[2], collect(session, [i for i in mid if i not in marked], 0.4),
             GREY, 0.9, alpha=0.9)
        draw(axes[2], collect(session, REFERENCE_FACES, 0.4), REFERENCE, 2.0)
        window(axes[2], 208, 18, 22, 5.5,
               "mid-web, r 200-225: a hole",
               "blue = the earlier pipeline's 6 faces, r 211.3-213.8")

        fig.tight_layout(rect=(0, 0, 1, 0.88))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=140, facecolor="white")
        print(f"written: {out_path}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
