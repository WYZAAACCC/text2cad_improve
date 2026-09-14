"""Map Agent-selected faces of a real TopoDS solid to FE mesh nodes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from seekflow_structural.core.pattern_solids import _explode_solids, _feature_entry, _open, _solid_facts
from seekflow_structural.core.role_facts import face_facts


def _read_nodes(mesh_inp: Path):
    nodes = {}
    for line in mesh_inp.read_text(encoding="utf-8", errors="replace").splitlines():
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


def _plane_distance(coord, facts):
    plane = facts.get("plane_axis")
    bbox = facts.get("bbox_mm")
    if not plane or not bbox:
        return None
    for i in range(3):
        if not (bbox[i] - 1e-4 <= coord[i] <= bbox[i + 3] + 1e-4):
            return None
    origin = plane["origin_mm"]
    normal = plane["direction"]
    return abs(
        (coord[0] - origin[0]) * normal[0]
        + (coord[1] - origin[1]) * normal[1]
        + (coord[2] - origin[2]) * normal[2]
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("mesh_inp", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tolerance-mm", type=float, default=1e-4)
    args = parser.parse_args()

    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    final = selection["final"]
    if not final.get("accepted"):
        raise SystemExit("selection was not accepted")
    feature_id = final.get("feature")
    if not feature_id:
        raise SystemExit("selection is missing feature")
    solid_index = int(final["solid_index"])
    selected_faces = [int(v) for v in final["selected_face_indices"]]

    session = _open(args.bundle.resolve())
    try:
        feature = _feature_entry(session, feature_id)
        shape = session.get_current_result_shape(
            feature.tag_path.resolve(session.main_label)
        )
        solids = _explode_solids(shape)
        _, faces = _solid_facts(solids[solid_index])
        nodes = _read_nodes(args.mesh_inp.resolve())
        per_face = {}
        counts = {}
        union = set()
        for face_index in selected_faces:
            facts = face_facts(faces[face_index])
            matches = []
            max_distance = 0.0
            for node_id, coord in nodes.items():
                distance = _plane_distance(coord, facts)
                if distance is None or distance > args.tolerance_mm:
                    continue
                matches.append(node_id)
                union.add(node_id)
                counts[node_id] = counts.get(node_id, 0) + 1
                max_distance = max(max_distance, distance)
            per_face[str(face_index)] = {
                "node_count": len(matches),
                "node_ids": matches,
                "max_plane_distance_mm": max_distance,
                "area_mm2": facts["area_mm2"],
                "centroid_mm": facts.get("centroid_mm"),
                "normal_xyz": facts.get("normal_xyz"),
                "normal_cylindrical": facts.get("normal_cylindrical"),
            }
        payload = {
            "bundle": str(args.bundle.resolve()),
            "mesh_inp": str(args.mesh_inp.resolve()),
            "feature": feature_id,
            "solid_index": solid_index,
            "selected_face_indices": selected_faces,
            "tolerance_mm": args.tolerance_mm,
            "mapped_face_count": sum(
                1 for row in per_face.values() if row["node_count"] > 0
            ),
            "union_node_count": len(union),
            "union_node_ids": sorted(union),
            "overlap_node_count": sum(1 for count in counts.values() if count > 1),
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
                        key: row["node_count"]
                        for key, row in per_face.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
