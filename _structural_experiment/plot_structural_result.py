"""Plot a generic radius-axial view of structural nodal results."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")


def _read_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8", errors="replace") as stream:
        for row in csv.DictReader(stream):
            try:
                value = float(row["s_eqv"].strip())
                if value <= 0:
                    continue
                rows.append(
                    {
                        "nid": int(float(row["nid"].strip())),
                        "r": math.hypot(
                            float(row["x"].strip()), float(row["y"].strip())
                        ),
                        "z": float(row["z"].strip()),
                        "s_eqv": value,
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("nodal_csv", type=Path)
    parser.add_argument("metrics_json", type=Path)
    parser.add_argument("output_png", type=Path)
    args = parser.parse_args()

    rows = _read_rows(args.nodal_csv.resolve())
    if not rows:
        raise SystemExit("no nodal stress values to plot")
    metrics = json.loads(args.metrics_json.read_text(encoding="utf-8"))

    fig, ax = plt.subplots(figsize=(11, 5.5))
    scatter = ax.scatter(
        [row["r"] for row in rows],
        [row["z"] for row in rows],
        c=[row["s_eqv"] for row in rows],
        s=5,
        cmap="turbo",
    )
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("radius from rotation axis [mm]")
    ax.set_ylabel("axial coordinate [mm]")
    ax.set_title(
        f"{metrics['case_id']} | max von Mises "
        f"{metrics['stress']['max_von_mises_mpa']:.3f} MPa"
    )
    colorbar = fig.colorbar(scatter, ax=ax, pad=0.02)
    colorbar.set_label("von Mises stress [MPa]")
    fig.tight_layout()
    args.output_png.resolve().parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output_png.resolve(), dpi=180)
    plt.close(fig)
    print(args.output_png.resolve())


if __name__ == "__main__":
    main()

