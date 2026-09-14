"""Draw the solved stress field so it can be looked at and judged.

Two things this has to get past. The r-z view the reporter draws is the right
picture for a field and the wrong one for the model: it collapses the azimuth,
so an 18 degree sector and a full disc look identical. And a 3D view of an
18 degree wedge is a thin curved slab from almost every angle, which shows the
extent and nothing else.

So the figure carries both, and the 3D half is spent where it earns its keep -
on the load region, drawn close enough to see the individual fir-tree flanks
and with the nodes that actually carry the load marked. The r-z half is scaled
twice, because on D27 the peak is at the bore at 1483 MPa and the loaded
flanks sit near 115 MPa: scaled to the peak every other feature is one flat
colour, and scaled to the flanks the bore saturates. Both are true.

    python plot_stress_3d.py <job-dir> <output.png>
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402

LOCAL_VMAX_MPA = 200.0
ZOOM_RADIUS_MM = 250.0


def read_nodes(csv_path: pathlib.Path):
    """Every node with a defined stress, keyed by node id."""
    out = {}
    with csv_path.open(newline="", encoding="utf-8", errors="replace") as s:
        for row in csv.DictReader(s):
            try:
                nid = int(float(row["nid"]))
                x = float(row["x"])
                y = float(row["y"])
                z = float(row["z"])
                value = float(row["s_eqv"])
            except (KeyError, TypeError, ValueError):
                continue
            if value <= 0:
                continue
            out[nid] = (x, y, z, math.hypot(x, y), value)
    return out


def loaded_nodes(path: pathlib.Path) -> set[int]:
    if not path.is_file():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(v) for v in payload.get("union_node_ids") or []}


def _cloud(ax, rows, vmax, loaded, *, marker=0.7):
    scatter = ax.scatter(
        [n[0] for n in rows], [n[1] for n in rows], [n[2] for n in rows],
        c=[n[4] for n in rows], s=marker, cmap="turbo", vmin=0.0, vmax=vmax,
        linewidths=0, rasterized=True,
    )
    if loaded:
        ax.scatter(
            [n[0] for n in loaded], [n[1] for n in loaded],
            [n[2] for n in loaded],
            s=marker * 0.6, c="black", linewidths=0, rasterized=True,
        )
    ax.set_xlabel("x [mm]", fontsize=7)
    ax.set_ylabel("y [mm]", fontsize=7)
    ax.set_zlabel("z [mm]", fontsize=7)
    ax.tick_params(labelsize=6, pad=0)
    return scatter


def _section(ax, rows, vmax, load_radius, title, *, xlim=None, marker=1.4):
    scatter = ax.scatter(
        [n[3] for n in rows], [n[2] for n in rows], c=[n[4] for n in rows],
        s=marker, cmap="turbo", vmin=0.0, vmax=vmax, linewidths=0,
        rasterized=True,
    )
    if xlim is None or xlim[0] <= load_radius <= xlim[1]:
        ax.axvline(
            load_radius, color="black", lw=0.8, ls="--", alpha=0.8,
            label=f"load radius {load_radius:.1f} mm",
        )
        ax.legend(fontsize=6, loc="upper left")
    if xlim is not None:
        ax.set_xlim(*xlim)
    ax.set_xlabel("radius from the axis [mm]", fontsize=8)
    ax.set_ylabel("z [mm]  (half thickness solved)", fontsize=8)
    ax.set_title(title, fontsize=9)
    ax.tick_params(labelsize=7)
    ax.set_aspect("equal", adjustable="box")
    return scatter


def main() -> int:
    job = pathlib.Path(sys.argv[1]).resolve()
    output = pathlib.Path(sys.argv[2]).resolve()
    solve = job / "solve"

    nodes = read_nodes(solve / "nodal_stress_3d.csv")
    if not nodes:
        raise SystemExit("no stressed nodes to draw")
    marked = loaded_nodes(solve / "selected_face_nodes.json")
    metrics = json.loads(
        (solve / "structural_metrics.json").read_text(encoding="utf-8")
    )
    peak = metrics["stress"]["max_von_mises_mpa"]
    load_peak = metrics["stress"]["max_load_surface_von_mises_mpa"]
    # The load radius is not in the metrics; it lives in the case, where the
    # stage that chose the faces wrote it, which is the only place it exists.
    case = json.loads((job / "case.json").read_text(encoding="utf-8"))
    radius = float((case.get("load_surface") or {}).get("load_radius_mm") or 0.0)

    rows = list(nodes.values())
    # One point in four for the wide 3D view: 257k markers is a smear, and the
    # field it draws is smooth. The zoom and the sections keep all of them.
    wide = rows[::4]
    zoom = [n for n in rows if n[3] >= ZOOM_RADIUS_MM]
    loaded_wide = [nodes[i] for i in marked if i in nodes][::2]
    loaded_zoom = [
        nodes[i] for i in marked if i in nodes and nodes[i][3] >= ZOOM_RADIUS_MM
    ]

    fig = plt.figure(figsize=(15.0, 10.4))

    ax = fig.add_subplot(2, 2, 1, projection="3d")
    scatter = _cloud(ax, wide, peak, loaded_wide)
    ax.set_title(
        f"the sector as solved, in full  |  0 - {peak:.0f} MPa", fontsize=9
    )
    ax.view_init(elev=26, azim=-58)
    ax.set_box_aspect((1.0, 1.0, 0.42))
    fig.colorbar(scatter, ax=ax, shrink=0.55, pad=0.08).set_label(
        "von Mises [MPa]", fontsize=7
    )

    ax = fig.add_subplot(2, 2, 2, projection="3d")
    scatter = _cloud(ax, zoom, LOCAL_VMAX_MPA, loaded_zoom)
    ax.set_title(
        f"the fir-tree slot, r >= {ZOOM_RADIUS_MM:.0f} mm  |  "
        f"0 - {LOCAL_VMAX_MPA:.0f} MPa  |  black = the loaded nodes",
        fontsize=9,
    )
    ax.view_init(elev=16, azim=-72)
    ax.set_box_aspect((1.0, 1.0, 0.5))
    fig.colorbar(scatter, ax=ax, shrink=0.55, pad=0.08).set_label(
        "von Mises [MPa]", fontsize=7
    )

    # The bore hot spot is a handful of nodes on a coarse mesh - 888 nodes
    # inside r=80 against 211 245 outside r=280 - so on the full section it is
    # invisible, and the peak that the safety factor is computed from is never
    # seen. This panel is the same data zoomed onto it.
    bore = [n for n in rows if n[3] <= 200.0]
    rim = [n for n in rows if n[3] >= 280.0]
    ax = fig.add_subplot(2, 2, 3)
    scatter = _section(
        ax, bore, peak, radius or 0.0,
        f"r <= 200 mm, where the peak is  |  0 - {peak:.0f} MPa  |  "
        f"{len(bore)} nodes",
        xlim=(50.0, 200.0),
    )
    fig.colorbar(scatter, ax=ax, shrink=0.8, pad=0.02).set_label(
        "von Mises [MPa]", fontsize=7
    )

    ax = fig.add_subplot(2, 2, 4)
    scatter = _section(
        ax, rows, LOCAL_VMAX_MPA, radius or 0.0,
        f"the same nodes  |  0 - {LOCAL_VMAX_MPA:.0f} MPa  |  "
        f"the loaded flanks peak at {load_peak:.0f} MPa",
    )
    fig.colorbar(scatter, ax=ax, shrink=0.8, pad=0.02).set_label(
        "von Mises [MPa]", fontsize=7
    )

    fig.suptitle(
        f"{metrics['case_id']}  |  {len(nodes)} nodes, 18 deg sector, half "
        f"thickness  |  peak {peak:.1f} MPa at r="
        f"{metrics['stress']['max_radius_mm']:.1f}  |  on the loaded flanks "
        f"{load_peak:.1f} MPa  |  {len(marked)} nodes carry the load\n"
        f"the mesh spends {100.0 * len(rim) / len(nodes):.0f}% of its nodes "
        f"outside r=280 and {len(bore)} nodes inside r=200, so the peak and "
        f"the minimum safety factor both sit on the coarsest mesh in the model",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=140)
    plt.close(fig)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
