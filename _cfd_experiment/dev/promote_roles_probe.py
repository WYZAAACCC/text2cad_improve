"""Probe: promote existing face roles to persistent selections on a copy."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "input" / "lineage" / "D01"
WORK = ROOT / "dev" / "prepared-D01"


def copy_bundle() -> Path:
    if WORK.exists():
        shutil.rmtree(WORK)
    shutil.copytree(INPUT, WORK)
    return WORK


def main() -> int:
    from seekflow_cfd.models import GeometryRef, SurfaceRef
    from seekflow_cfd.storage import atomic_json, file_hash
    from seekflow_cfd.topology import OCAFTopology
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

    bundle = copy_bundle()
    xbf = bundle / "design.xbf"
    step = bundle / "model.step"
    history = bundle / "history.json"

    session = OcafDocumentSession.open(xbf)
    try:
        feature_entries = [
            e
            for e in session.label_index.entries()
            if e.retired_revision is None and e.key.object_kind == "feature"
        ]
        if not feature_entries:
            print("no feature entries")
            return 2
        role_entries = [
            e
            for e in session.label_index.entries()
            if e.retired_revision is None and e.key.object_kind == "face_role"
        ]
        print("features", len(feature_entries), "face roles", len(role_entries))
        service = PersistentSelectionService(session)
        created = 0
        for entry in role_entries:
            feature_entry = feature_entries[0]
            feature_label = feature_entry.tag_path.resolve(session.main_label)
            role_tag = entry.tag_path.tags[-1]
            shape = session.get_current_role_result(feature_label, role_tag)
            if shape is None:
                print("no shape for", entry.key.object_id)
                continue
            context = session.get_current_result_shape(feature_label)
            if context is None:
                print("no context for", feature_entry.key.object_id)
                continue
            safe_id = "fr::" + entry.key.namespace + "::" + entry.key.object_id
            policy = SelectionPolicy(
                entity_kind=TopologyEntityKind.FACE,
                cardinality=SelectionCardinality.EXACT_ONE,
                split_strategy=None,
                allow_deleted=False,
            )
            service.create(safe_id, shape, context, policy)
            created += 1
        session.set_lineage_metadata("D01")
        session.label_index.save_to_ocaf(session.main_label)
        temp = session.save_temp(bundle)
        session.close()
        OcafDocumentSession.publish(temp, xbf)
        print("created selections", created)
    except Exception:
        session.close()
        raise

    new = OcafDocumentSession.open(xbf)
    try:
        print("new meta", new.get_lineage_metadata())
        print("new labels", len(new.label_index.entries()))
        selections = [
            e.key.object_id
            for e in new.label_index.entries()
            if e.retired_revision is None and e.key.object_kind == "selection"
        ]
        print("selection count", len(selections), "first", selections[:2])
    finally:
        new.close()

    history_data = __import__("json").loads(history.read_text(encoding="utf-8"))
    history_data["topology_hash"] = file_hash(xbf)
    history_data["ocaf_label_count"] = None
    history_data["ocaf_revision"] = 1
    history_data["provenance"] = (
        "XBF lineage metadata and role selections written by topology prepare probe"
    )
    atomic_json(history, history_data)
    ref = GeometryRef(
        lineage_id="D01",
        revision_id="rev-000001",
        cad_record_id="cfd-probe-D01",
        geometry={"path": "model.step", "sha256": file_hash(step)},
        topology={"path": "design.xbf", "sha256": file_hash(xbf)},
        history_evidence={
            "path": "history.json",
            "sha256": file_hash(history),
        },
        length_unit="mm",
    )
    bridge = OCAFTopology(bundle, ref)
    try:
        roles = bridge.list_topology_roles()
        selection_roles = [r for r in roles if r["kind"] == "selection"]
        print("bridge selection roles", len(selection_roles))
        if selection_roles:
            key = selection_roles[0]["key"]
            binding = bridge.resolve_role_to_faces(
                SurfaceRef(source="selection", key=key)
            )
            print("binding", binding.model_dump(mode="json"))
    finally:
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
