"""Export Agent-selected persistent roles as named BRep boundary artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cadquery as cq

STRUCTURAL_ROOT = Path(__file__).resolve().parents[1]
if str(STRUCTURAL_ROOT) not in sys.path:
    sys.path.insert(0, str(STRUCTURAL_ROOT))

from OCP.TopAbs import TopAbs_FACE  # noqa: E402

from seekflow_structural.core.pattern_solids import (  # noqa: E402
    _explode_solids,
    _feature_entry,
    _open,
    _solid_facts,
)
from seekflow_structural.core.role_facts import face_facts  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_face_id(canonical_face_id: str) -> tuple[int, int]:
    parts = canonical_face_id.split(":solid:", 1)
    if len(parts) != 2 or ":face:" not in parts[1]:
        raise ValueError(f"invalid canonical face id: {canonical_face_id}")
    solid_text, face_text = parts[1].split(":face:", 1)
    return int(solid_text), int(face_text)


def _resolve_role(session, role_id: str):
    if "|" not in role_id:
        raise ValueError(f"invalid role id: {role_id}")
    namespace, role_key = role_id.split("|", 1)
    entry = session.label_index.get_existing("face_role", namespace, role_key)
    if entry is None or entry.retired_revision is not None:
        raise ValueError(f"inactive role: {role_id}")
    role_label = entry.tag_path.resolve(session.main_label)
    feature_label = role_label.Father().Father()
    shape = session.get_current_role_result(feature_label, role_label.Tag())
    if shape is None or shape.ShapeType() != TopAbs_FACE:
        raise ValueError(f"role does not resolve to a face: {role_id}")
    return shape


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--feature", default="n_final_cut")
    args = parser.parse_args()

    bundle = args.bundle.resolve()
    history = json.loads((bundle / "history.json").read_text(encoding="utf-8"))
    payload = json.loads(args.selection.read_text(encoding="utf-8"))
    final = payload["final"]
    if not final.get("accepted"):
        raise SystemExit("Agent selection was not accepted")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    session = _open(bundle)
    try:
        feature = _feature_entry(session, args.feature)
        result_shape = session.get_current_result_shape(
            feature.tag_path.resolve(session.main_label)
        )
        solids = _explode_solids(result_shape)
        bindings = {}
        metadata = {}
        for index, item in enumerate(final["selection"]):
            canonical_face_id = item["canonical_face_id"]
            role_id = item["role_id"]
            solid_index, face_index = _parse_face_id(canonical_face_id)
            _, faces = _solid_facts(solids[solid_index])
            final_face = faces[face_index]
            role_face = _resolve_role(session, role_id)
            if not final_face.IsSame(role_face):
                raise ValueError(
                    f"role {role_id} does not resolve to {canonical_face_id}"
                )
            filename = f"selected_role_{index:03d}.brep"
            path = output_dir / filename
            cq.Shape.cast(role_face).exportBrep(str(path))
            binding = {
                "source_key": role_id,
                "status": "unique",
                "proof": "exact_kernel_history",
                "entity_kind": "face",
                "entity_ids": [role_id],
                "lineage_id": history["lineage_id"],
                "revision_id": history["revision_id"],
                "geometry_hash": history["geometry_hash"],
                "history_complete": True,
                "provenance": f"OCAF face_role resolved live: {role_id}",
                "parent_entity_ids": [],
                "native_face_artifacts": {role_id: filename},
            }
            bindings[role_id] = binding
            metadata[role_id] = {
                "canonical_face_id": canonical_face_id,
                "role_id": role_id,
                "face_facts": face_facts(role_face),
                "brep_sha256": _sha256(path),
            }
        output = {
            "schema_version": "role_face_export_v1",
            "bundle": str(bundle),
            "feature": args.feature,
            "persistent_identity_status": "persistent_role_resolved",
            "bindings": bindings,
            "selection_metadata": metadata,
        }
        (output_dir / "selected_roles.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "output_dir": str(output_dir),
                    "exported_role_count": len(bindings),
                    "persistent_identity_status": "persistent_role_resolved",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()

