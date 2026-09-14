"""Export Agent-selected TopoDS faces as exact BRep artifacts.

This tool does not claim persistent role identity. Its output explicitly marks
index-only bindings until an independent native role mapping is available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cadquery as cq

from seekflow_structural.core.pattern_solids import (
    _explode_solids,
    _feature_entry,
    _open,
    _solid_facts,
)
from seekflow_structural.core.role_facts import face_facts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--key-prefix", default="selected_face")
    args = parser.parse_args()

    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    final = selection["final"]
    if not final.get("accepted"):
        raise SystemExit("selection was not accepted")
    feature_id = final.get("feature")
    if not feature_id:
        raise SystemExit("selection is missing feature")
    solid_index = int(final["solid_index"])
    selected_faces = [int(value) for value in final["selected_face_indices"]]

    session = _open(args.bundle.resolve())
    try:
        history = json.loads(
            (args.bundle / "history.json").read_text(encoding="utf-8")
        )
        feature = _feature_entry(session, feature_id)
        shape = session.get_current_result_shape(
            feature.tag_path.resolve(session.main_label)
        )
        solids = _explode_solids(shape)
        _, faces = _solid_facts(solids[solid_index])
        output_dir = args.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts = {}
        bindings = {}
        metadata = {}
        for face_index in selected_faces:
            key = f"{args.key_prefix}_{face_index:03d}"
            filename = key + ".brep"
            path = output_dir / filename
            cq.Shape.cast(faces[face_index]).exportBrep(str(path))
            facts = face_facts(faces[face_index])
            entity_id = f"index_only:{solid_index}:{face_index}"
            binding = {
                "source_key": key,
                "status": "unique",
                "proof": "exact_construction",
                "entity_kind": "face",
                "entity_ids": [entity_id],
                "lineage_id": history["lineage_id"],
                "revision_id": history["revision_id"],
                "geometry_hash": history["geometry_hash"],
                "history_complete": True,
                "provenance": (
                    "Agent-selected TopoDS face exported by temporary index; "
                    "native persistent role mapping is still required"
                ),
                "parent_entity_ids": [],
                "native_face_artifacts": {entity_id: filename},
            }
            artifacts[key] = binding
            metadata[key] = {
                "persistent_identity_status": "role_mapping_pending",
                "feature": feature_id,
                "solid_index": solid_index,
                "face_index": face_index,
                "face_facts": facts,
                "brep_sha256": _sha256(path),
            }
            bindings[key] = artifacts[key]
        payload = {
            "schema_version": "selected_face_export_v1",
            "bundle": str(args.bundle.resolve()),
            "feature": feature_id,
            "solid_index": solid_index,
            "selected_face_indices": selected_faces,
            "persistent_identity_status": "role_mapping_pending",
            "bindings": bindings,
            "selection_metadata": metadata,
        }
        (output_dir / "selected_faces.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "output_dir": str(output_dir),
                    "exported_face_count": len(bindings),
                    "persistent_identity_status": "role_mapping_pending",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
