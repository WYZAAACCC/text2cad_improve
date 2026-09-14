"""Map persistent planar face roles to FE mesh nodes.

Only generic plane/bbox facts are used. The tool does not know slot semantics
and does not select faces; it consumes an agent-authored role selection.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from seekflow_structural.core.role_facts import RoleCatalog


def _read_nodes(mesh_inp: Path):
    nodes = {}
    with mesh_inp.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith("N,"):
                continue
            parts = line.strip().split(",")
            if len(parts) != 5:
                continue
            try:
                nodes[int(parts[1])] = tuple(float(v) for v in parts[2:5])
            except ValueError:
                continue
    return nodes


def _plane_membership(coord, facts, tolerance_mm):
    bbox = facts.get("bbox_mm")
    plane = facts.get("plane_axis")
    if not bbox or not plane:
        return None
    x, y, z = coord
    xmin, ymin, zmin, xmax, ymax, zmax = bbox
    if not (
        xmin - tolerance_mm <= x <= xmax + tolerance_mm
        and ymin - tolerance_mm <= y <= ymax + tolerance_mm
        and zmin - tolerance_mm <= z <= zmax + tolerance_mm
    ):
        return None
    origin = plane["origin_mm"]
    normal = plane["direction"]
    distance = abs(
        (x - origin[0]) * normal[0]
        + (y - origin[1]) * normal[1]
        + (z - origin[2]) * normal[2]
    )
    if distance <= tolerance_mm:
        return distance
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("mesh_inp", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tolerance-mm", type=float, default=1e-4)
    args = parser.parse_args()

    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    selected = selection["final"]["selected_roles"]
    nodes = _read_nodes(args.mesh_inp.resolve())
    catalog = RoleCatalog(args.bundle)
    try:
        per_face = {}
        all_nodes = set()
        node_face_count = {}
        for encoded in selected:
            namespace, key = encoded.split("|", 1)
            facts = catalog.facts(namespace, key)
            matches = []
            max_distance = 0.0
            for node_id, coord in nodes.items():
                distance = _plane_membership(
                    coord, facts, args.tolerance_mm
                )
                if distance is None:
                    continue
                matches.append(node_id)
                max_distance = max(max_distance, distance)
                node_face_count[node_id] = node_face_count.get(node_id, 0) + 1
            all_nodes.update(matches)
            per_face[encoded] = {
                "node_count": len(matches),
                "node_ids": matches,
                "max_plane_distance_mm": max_distance,
                "surface_type": facts.get("surface_type"),
                "area_mm2": facts.get("area_mm2"),
            }
        overlaps = {
            str(node_id): count
            for node_id, count in node_face_count.items()
            if count > 1
        }
        payload = {
            "bundle": str(args.bundle.resolve()),
            "mesh_inp": str(args.mesh_inp.resolve()),
            "tolerance_mm": args.tolerance_mm,
            "selected_role_count": len(selected),
            "mapped_face_count": sum(
                1 for record in per_face.values() if record["node_count"] > 0
            ),
            "union_node_count": len(all_nodes),
            "union_node_ids": sorted(all_nodes),
            "overlap_node_count": len(overlaps),
            "overlaps": overlaps,
            "per_face": per_face,
        }
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.output.resolve().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "mapped_face_count": payload["mapped_face_count"],
                    "union_node_count": payload["union_node_count"],
                    "overlap_node_count": payload["overlap_node_count"],
                    "faces": {
                        key: value["node_count"]
                        for key, value in per_face.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        catalog.close()


if __name__ == "__main__":
    main()
