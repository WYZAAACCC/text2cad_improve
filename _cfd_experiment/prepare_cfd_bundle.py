"""Prepare an immutable CFD input bundle from a generated CAD lineage.

The preparer copies a real Dxx product directory and makes two auditable
modifications on the copy only:

1. Write XBF lineage metadata so GeometryRef validation can bind the files.
2. Promote the face roles that survive in the final feature result to
   persistent selections. Each final face is represented by one semantic role
   selection when a native role face with the same TShape exists.

No main-flow files are modified and no geometry/STEP content is regenerated.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
    OcafDocumentSession,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionCardinality,
    SelectionPolicy,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
    PersistentSelectionService,
)
from seekflow_cfd.storage import file_hash

REQUIRED = ("model.step", "design.xbf", "history.json", "output.metadata.json")


def _copied_bundle(input_dir: Path, output_dir: Path) -> Path:
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(input_dir, output_dir)
    missing = [name for name in REQUIRED if not (output_dir / name).is_file()]
    if missing:
        raise SystemExit(f"input bundle missing required files: {missing}")
    return output_dir


def _role_tag_from_entry(entry) -> int:
    return entry.tag_path.tags[-1]


def _final_exterior_selections(session, entries):
    features = {
        e.key.object_id: e for e in entries if e.key.object_kind == "feature"
    }
    if not features:
        raise SystemExit("XBF contains no feature entries")
    final_id = max(features, key=lambda key: features[key].tag_path.tags)
    final_entry = features[final_id]
    final_label = final_entry.tag_path.resolve(session.main_label)
    final_shape = session.get_current_result_shape(final_label)
    if final_shape is None:
        raise SystemExit("final feature current result is unavailable")

    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer

    final_faces = []
    explorer = TopExp_Explorer(final_shape, TopAbs_FACE)
    while explorer.More():
        final_faces.append(explorer.Current())
        explorer.Next()

    selected = []  # (role_entry, final_face_index)
    used = set()
    for entry in entries:
        if entry.key.object_kind != "face_role":
            continue
        feature_id = entry.key.namespace.removeprefix("feature:")
        feature_entry = features.get(feature_id)
        if feature_entry is None:
            continue
        feature_label = feature_entry.tag_path.resolve(session.main_label)
        role_shape = session.get_current_role_result(
            feature_label, _role_tag_from_entry(entry)
        )
        if role_shape is None or role_shape.IsNull():
            continue
        for index, face in enumerate(final_faces):
            if index in used:
                continue
            try:
                if role_shape.IsSame(face):
                    selected.append((entry, index))
                    used.add(index)
                    break
            except Exception:  # pragma: no cover - OCP IsSame boundary guard
                continue
    return final_id, final_faces, selected


def prepare(input_dir: Path, output_dir: Path, lineage_id: str) -> dict:
    bundle = _copied_bundle(input_dir, output_dir)
    xbf = bundle / "design.xbf"
    history = bundle / "history.json"
    step = bundle / "model.step"

    session = OcafDocumentSession.open(xbf)
    try:
        entries = [
            e for e in session.label_index.entries() if e.retired_revision is None
        ]
        final_id, final_faces, selected = _final_exterior_selections(session, entries)
        if not selected:
            raise SystemExit(
                "no final-exterior role faces found; refusing to invent selections"
            )

        service = PersistentSelectionService(session)
        policy = SelectionPolicy(
            entity_kind=TopologyEntityKind.FACE,
            cardinality=SelectionCardinality.EXACT_ONE,
            split_strategy=None,
            allow_deleted=False,
        )
        created = 0
        for role_entry, index in selected:
            selection_id = (
                "fr::" + role_entry.key.namespace + "::" + role_entry.key.object_id
            )
            feature_id = role_entry.key.namespace.removeprefix("feature:")
            feature_entry = next(
                e for e in entries if e.key.object_kind == "feature"
                and e.key.object_id == feature_id
            )
            feature_label = feature_entry.tag_path.resolve(session.main_label)
            role_shape = session.get_current_role_result(
                feature_label, _role_tag_from_entry(role_entry)
            )
            context_shape = session.get_current_result_shape(feature_label)
            service.create(selection_id, role_shape, context_shape, policy)
            created += 1

        session.set_lineage_metadata(lineage_id)
        session.label_index.save_to_ocaf(session.main_label)
        temp = session.save_temp(bundle)
        session.close()
        OcafDocumentSession.publish(temp, xbf)
    except Exception:
        session.close()
        raise

    reopened = OcafDocumentSession.open(xbf)
    try:
        entries = [
            e for e in reopened.label_index.entries() if e.retired_revision is None
        ]
        selection_count = sum(
            1 for e in entries if e.key.object_kind == "selection"
        )
        meta = reopened.get_lineage_metadata()
    finally:
        reopened.close()

    data = json.loads(history.read_text(encoding="utf-8"))
    data["topology_hash"] = file_hash(xbf)
    data["ocaf_label_count"] = len(entries)
    data["ocaf_revision"] = 1
    data["provenance"] = (
        "cfd-bundle-preparer: lineage metadata and final-exterior role "
        "selections written on an immutable copy"
    )
    from seekflow_cfd.storage import atomic_json

    atomic_json(history, data)
    summary = {
        "lineage_id": lineage_id,
        "final_feature": final_id,
        "final_faces": len(final_faces),
        "role_selections_created": created,
        "selection_count": selection_count,
        "lineage_metadata": meta,
        "history_hash": file_hash(history),
        "topology_hash": data["topology_hash"],
        "geometry_hash": file_hash(step),
    }
    atomic_json(bundle / "cfd_input_manifest.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--lineage", default=None, help="defaults to input dir name")
    args = parser.parse_args()
    lineage = args.lineage or args.input.resolve().name
    print(json.dumps(prepare(args.input, args.output, lineage), ensure_ascii=False))


if __name__ == "__main__":
    main()
