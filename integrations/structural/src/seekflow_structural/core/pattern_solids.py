"""Generic OCAF feature-result decomposition into connected solids.

No structural or slot-specific logic lives here. It exposes actual TopoDS
solid components and exact persistent face-role identity for Agent selection.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/engineering_tools/src"))

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (  # noqa: E402
    OcafDocumentSession,
)
from seekflow_structural.core.role_facts import face_facts  # noqa: E402


def _feature_entries(session):
    return [
        entry
        for entry in session.label_index.entries()
        if entry.retired_revision is None and entry.key.object_kind == "feature"
    ]


def _feature_entry(session, feature_id: str):
    matches = [
        entry
        for entry in _feature_entries(session)
        if entry.key.object_id == feature_id
    ]
    if len(matches) != 1:
        raise KeyError(
            f"feature id {feature_id!r} resolved to {len(matches)} entries"
        )
    return matches[0]


def _load_solids(session, feature):
    """The solids a named feature's boolean produced.

    Lives here rather than in the face-selecting agent because it is a
    geometry operation and several callers need it - the distance-and-load
    measurement among them. When it lived in the agent, a core module had to
    import an agent to reach it, which is the dependency pointing the wrong
    way.
    """
    if not feature:
        raise ValueError("feature must name a feature returned by list_features")
    entry = _feature_entry(session, feature)
    shape = session.get_current_result_shape(
        entry.tag_path.resolve(session.main_label)
    )
    if shape is None:
        raise RuntimeError("feature result missing")
    return _explode_solids(shape)


def _solid_facts(solid):
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid, props)
    centre = props.CentreOfMass()
    bnd = Bnd_Box()
    BRepBndLib.Add_s(solid, bnd)
    bbox = list(bnd.Get())
    faces = []
    face_explorer = TopExp_Explorer(solid, TopAbs_FACE)
    while face_explorer.More():
        faces.append(TopoDS.Face_s(face_explorer.Current()))
        face_explorer.Next()
    r = math.hypot(centre.X(), centre.Y())
    return {
        "volume_mm3": float(props.Mass()),
        "centroid_mm": [centre.X(), centre.Y(), centre.Z()],
        "centroid_cyl_mm_deg": [
            r,
            math.degrees(math.atan2(centre.Y(), centre.X())),
            centre.Z(),
        ],
        "bbox_mm": bbox,
        "face_count": len(faces),
    }, faces


def _explode_solids(shape):
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    solids = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        solids.append(TopoDS.Solid_s(explorer.Current()))
        explorer.Next()
    return solids


def _role_face_map(session, target_faces):
    """Map exact TShape faces to persistent face-role keys."""
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    target_set = list(target_faces)
    result: dict[int, str] = {}
    role_entries = [
        entry
        for entry in session.label_index.entries()
        if entry.retired_revision is None and entry.key.object_kind == "face_role"
    ]
    for entry in role_entries:
        role_label = entry.tag_path.resolve(session.main_label)
        feature_label = role_label.Father().Father()
        role_shape = session.get_current_role_result(
            feature_label, role_label.Tag()
        )
        if role_shape is None or role_shape.ShapeType() != TopAbs_FACE:
            continue
        role_face = TopoDS.Face_s(role_shape)
        for index, target in enumerate(target_set):
            try:
                if role_face.IsSame(target) or role_face.IsPartner(target):
                    result[index] = (
                        entry.key.namespace + "|" + entry.key.object_id
                    )
            except Exception:
                continue
    return result


def _open(bundle: Path):
    return OcafDocumentSession.open(bundle / "design.xbf")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("features")
    solids_parser = sub.add_parser("solids")
    solids_parser.add_argument("--feature", required=True)
    sub.add_parser("solid-faces").add_argument("--feature", required=True)
    sub.choices["solid-faces"].add_argument("--index", type=int, required=True)
    sub.choices["solid-faces"].add_argument(
        "--with-persistent-roles", action="store_true"
    )
    args = parser.parse_args()

    bundle = args.bundle.resolve()
    session = _open(bundle)
    try:
        if args.command == "features":
            print(
                json.dumps(
                    [
                        {
                            "namespace": entry.key.namespace,
                            "key": entry.key.object_id,
                        }
                        for entry in _feature_entries(session)
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        entry = _feature_entry(session, args.feature)
        feature_label = entry.tag_path.resolve(session.main_label)
        shape = session.get_current_result_shape(feature_label)
        if shape is None:
            raise RuntimeError("feature has no current result shape")
        solids = _explode_solids(shape)
        if args.command == "solids":
            result = []
            for index, solid in enumerate(solids):
                facts, _ = _solid_facts(solid)
                facts["solid_index"] = index
                result.append(facts)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if args.index < 0 or args.index >= len(solids):
            raise IndexError("solid index out of range")
        facts, faces = _solid_facts(solids[args.index])
        role_map = (
            _role_face_map(session, faces) if args.with_persistent_roles else {}
        )
        result = {
            "feature": args.feature,
            "solid_index": args.index,
            "solid": facts,
            "faces": [
                {
                    "face_index": index,
                    "facts": face_facts(face),
                    "persistent_role": role_map.get(index),
                }
                for index, face in enumerate(faces)
            ],
            "mapped_face_count": len(role_map),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        session.close()


if __name__ == "__main__":
    main()
