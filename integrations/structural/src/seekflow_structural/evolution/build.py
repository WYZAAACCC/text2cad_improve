"""Building the face-evolution index, in the time the work actually needs.

The first version of this took about three hours on a 4,216-face part, and
almost none of that was the work. Two things made it expensive, and both are
avoidable:

  - **It resolved every role.** A part records far more than face provenance.
    On the reference part, 15,576 of 19,792 roles were edge and vertex history
    that is never offered as a face candidate - 79% of the reading, none of the
    answer. Those are now classified from the role key alone and never opened.

  - **Every bad attribute cost a process.** Reading a corrupt `TNaming` attribute
    faults natively, so it cannot be caught; the mitigation is to run batches in
    subprocesses and bisect a batch that dies. That is the right mitigation and
    it is ruinous at scale - 319 bad roles produced a bisection tree of about
    600 process starts, and each start reloads the whole document. Measured on
    the reference part: 10.5 s for 500 roles, 14.8 s for 2,292, so the load is
    around ten seconds and the resolution is about two milliseconds a role.
    The cost was never the roles. It was the starts.

So the work is arranged around starts. Roles whose kind is not face-level are
classified without opening anything. `carry` roles - a face passed through an
operation unchanged, which is exactly the kind that faults - are matched
against the operand body instead of being read, which removes the fault source
rather than recovering from it. What remains is resolved in a handful of large
batches, and the bisection stays as a fallback that should never fire.

The operand for the carry roles is *found*, not named. A boolean's target is
the feature before it, but which feature that is comes from trying each
candidate and keeping the one that matches, so the builder carries no part's
name in it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from seekflow_structural.core.pattern_solids import (
    _explode_solids,
    _feature_entry,
    _open,
    _solid_facts,
)
from seekflow_structural.core.role_facts import face_facts
from seekflow_structural.evolution import store

# What each role key means, decided without opening the document.
FACE_LEVEL_MARKERS = ("/mod/", "/final/")
SKIP_MARKERS = ("/gen/",)
CARRY_MARKER = "/carry"

# Roles per subprocess. Large on purpose: measured at about 2 ms a role against
# a ten second document load, so batches should be big enough that the load
# stops being the cost, and small enough that losing one to a fault is cheap.
DEFAULT_BATCH = 2000


@dataclass
class BuildReport:
    namespace: str
    revision_id: str
    canonical_faces: int = 0
    roles_total: int = 0
    roles_resolved: int = 0
    roles_not_face: int = 0
    roles_unresolved: int = 0
    roles_errored: int = 0
    resolved_by_kind: dict = field(default_factory=dict)
    carry_operand: str = ""
    carry_candidates: dict = field(default_factory=dict)
    batches: int = 0
    quarantined: int = 0
    seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            "namespace": self.namespace,
            "revision_id": self.revision_id,
            "canonical_faces": self.canonical_faces,
            "roles_total": self.roles_total,
            "roles_resolved": self.roles_resolved,
            "roles_not_face": self.roles_not_face,
            "roles_unresolved": self.roles_unresolved,
            "roles_errored": self.roles_errored,
            "resolved_by_kind": self.resolved_by_kind,
            "carry_operand": self.carry_operand,
            "carry_candidates": self.carry_candidates,
            "batches": self.batches,
            "quarantined": self.quarantined,
            "seconds": round(self.seconds, 1),
        }


def classify(role_key: str) -> str:
    """What a role is, from its key alone."""
    if CARRY_MARKER in role_key:
        return "carry"
    for marker in FACE_LEVEL_MARKERS:
        if marker in role_key:
            return "face_level"
    for marker in SKIP_MARKERS:
        if marker in role_key:
            return "history"
    return "other"


def role_records(session, namespace: str) -> list[dict]:
    """Every role of a namespace, with what is known without opening a shape."""
    out = []
    for entry in session.label_index.entries():
        if entry.retired_revision is not None:
            continue
        if entry.key.object_kind != "face_role":
            continue
        if entry.key.namespace != namespace:
            continue
        role_key = entry.key.object_id
        kind = classify(role_key)
        source_key = ""
        for marker in ("/mod/", "/gen/", "/final/", "/carry"):
            if marker in role_key:
                source_key = role_key.split(marker, 1)[0]
                break
        out.append({
            "role_id": f"{namespace}|{role_key}",
            "revision_id": "",
            "namespace": namespace,
            "feature_id": namespace.split(":", 1)[-1],
            "role_key": role_key,
            "role_tag": 0,
            "label_path": list(entry.tag_path.tags),
            "label_path_json": json.dumps(
                list(entry.tag_path.tags), ensure_ascii=False
            ),
            "created_revision": entry.created_revision
            if hasattr(entry, "created_revision") else None,
            "relation_kind": {
                "face_level": "modified", "carry": "carry", "history": "generated"
            }.get(kind, "role"),
            "source_key": source_key,
            "operation_id": None,
            "_class": kind,
        })
    return out


def measure_canonical(session, feature_id: str, revision_id: str) -> list[dict]:
    """The finished part's faces, measured, as index rows."""
    feature = _feature_entry(session, feature_id)
    shape = session.get_current_result_shape(
        feature.tag_path.resolve(session.main_label)
    )
    if shape is None:
        raise RuntimeError(f"feature {feature_id!r} has no current shape")
    rows = []
    for solid_index, solid in enumerate(_explode_solids(shape)):
        _facts, faces = _solid_facts(solid)
        for face_index, face in enumerate(faces):
            facts = face_facts(face)
            cylindrical = facts.get("centroid_cyl_mm_deg") or [0.0, 0.0, 0.0]
            normal = facts.get("normal_cylindrical") or {}
            centroid = facts.get("centroid_mm") or [0.0, 0.0, 0.0]
            bbox = facts.get("bbox_mm")
            rows.append({
                "canonical_face_id": store.face_id(
                    revision_id, solid_index, face_index
                ),
                "revision_id": revision_id,
                "feature_id": feature_id,
                "solid_index": solid_index,
                "face_index": face_index,
                "surface_type": facts.get("surface_type") or "unknown",
                "area_mm2": float(facts.get("area_mm2") or 0.0),
                "centroid_x": float(centroid[0]),
                "centroid_y": float(centroid[1]),
                "centroid_z": float(centroid[2]),
                "radius_mm": float(cylindrical[0]),
                "theta_deg": float(cylindrical[1]),
                "z_mm": float(cylindrical[2]),
                "normal_x": (facts.get("normal_xyz") or [None] * 3)[0],
                "normal_y": (facts.get("normal_xyz") or [None] * 3)[1],
                "normal_z": (facts.get("normal_xyz") or [None] * 3)[2],
                "normal_radial": normal.get("radial"),
                "normal_tangential": normal.get("tangential"),
                "normal_axial": normal.get("axial"),
                "bbox_json": json.dumps(bbox, ensure_ascii=False) if bbox else None,
                "fact_json": json.dumps(facts, ensure_ascii=False),
            })
    return rows


def _faces_of(session, feature_id: str) -> list:
    feature = _feature_entry(session, feature_id)
    shape = session.get_current_result_shape(
        feature.tag_path.resolve(session.main_label)
    )
    if shape is None:
        return []
    faces = []
    for solid in _explode_solids(shape):
        _facts, solid_faces = _solid_facts(solid)
        faces.extend(solid_faces)
    return faces


def _carry_index(role: dict) -> int:
    return int(role["source_key"].rsplit("_", 1)[-1])


def _locator(facts: dict) -> tuple:
    """A key that identifies a face by what was measured about it.

    A carried face is unchanged, so its measurements repeat to the last bit
    when it is measured again in the operand - which makes the measurements
    themselves the way to find it, and costs a dictionary lookup instead of a
    full comparison against every face of the part.
    """
    centroid = facts.get("centroid_mm") or [0.0, 0.0, 0.0]
    return (
        round(float(facts.get("area_mm2") or 0.0), 6),
        round(float(centroid[0]), 6),
        round(float(centroid[1]), 6),
        round(float(centroid[2]), 6),
    )


def recover_carry(session, roles: list[dict], final_feature: str,
                  candidate_features: list[str]) -> tuple[list[dict], str, dict]:
    """Match carried faces against the body they were carried from.

    A `carry` role names a face that passed through the operation untouched,
    so the same face is present in the operand and can be found by looking for
    it rather than by reading an attribute that, on this kind of role, is the
    one most likely to fault. That is the point: this replaces the source of
    the native faults instead of recovering from them.

    Which feature the operand is gets worked out by trying them and keeping
    the one that matches the most carries. Naming it would put a part's
    feature name in the builder, and the first attempt at this did exactly
    that - it named the wrong feature for a second part and reported "carry
    match count 0", which reads as a geometry mismatch rather than as looking
    in the wrong place.
    """
    final_faces = _faces_of(session, final_feature)
    by_locator: dict[tuple, int] = {}
    for position, face in enumerate(final_faces):
        by_locator.setdefault(_locator(face_facts(face)), position)

    indices = [_carry_index(role) for role in roles]
    scores: dict[str, int] = {}
    winner, winner_faces = "", None
    for candidate in candidate_features:
        faces = _faces_of(session, candidate)
        if not faces or max(indices, default=-1) >= len(faces):
            scores[candidate] = 0
            continue
        matched = sum(
            1 for index in indices
            if _locator(face_facts(faces[index])) in by_locator
        )
        scores[candidate] = matched
        if winner_faces is None or matched > scores[winner]:
            winner, winner_faces = candidate, faces

    if winner_faces is None or scores.get(winner, 0) == 0:
        # Said plainly rather than resolved to something plausible: without an
        # operand there is nothing to match against, and a guess here would
        # attach wrong faces to names that are supposed to be stable.
        return (
            [dict(role, resolution_status="unresolved",
                  error="no operand feature matched these carries")
             for role in roles],
            "",
            scores,
        )

    resolved = []
    for role in roles:
        index = _carry_index(role)
        source = winner_faces[index]
        facts = face_facts(source)
        position = by_locator.get(_locator(facts))
        if position is None:
            resolved.append(dict(
                role, resolution_status="unresolved",
                error="carried face is not in the finished part",
            ))
            continue
        cylindrical = facts.get("centroid_cyl_mm_deg") or [0.0, 0.0, 0.0]
        normal = facts.get("normal_cylindrical") or {}
        centroid = facts.get("centroid_mm") or [0.0, 0.0, 0.0]
        resolved.append(dict(
            role,
            resolution_status="resolved",
            resolution_method="operand_shape_match",
            resolved_face_id=store.face_id(role["revision_id"], 0, position),
            solid_index=0,
            face_index=position,
            surface_type=facts.get("surface_type"),
            area_mm2=float(facts.get("area_mm2") or 0.0),
            centroid_x=float(centroid[0]),
            centroid_y=float(centroid[1]),
            centroid_z=float(centroid[2]),
            radius_mm=float(cylindrical[0]),
            theta_deg=float(cylindrical[1]),
            z_mm=float(cylindrical[2]),
            normal_radial=normal.get("radial"),
            normal_tangential=normal.get("tangential"),
            normal_axial=normal.get("axial"),
            fact_json=json.dumps(facts, ensure_ascii=False),
        ))
    return resolved, winner, scores


def resolve_batch(bundle: Path, batch: list[dict], canonical: list[dict],
                  revision_id: str, final_feature: str) -> list[dict]:
    """Resolve one batch, bisecting only if the subprocess dies."""
    if not batch:
        return []
    payload = {
        "revision_id": revision_id,
        "final_feature": final_feature,
        "canonical": canonical,
        "batch": batch,
    }
    with tempfile.TemporaryDirectory() as tmp:
        batch_path = Path(tmp) / "batch.json"
        out_path = Path(tmp) / "out.jsonl"
        batch_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        completed = subprocess.run(
            [sys.executable, "-m", "seekflow_structural.evolution.resolve",
             str(bundle), str(batch_path), str(out_path)],
            capture_output=True, text=True,
        )
        if completed.returncode != 0:
            if len(batch) == 1:
                return [dict(batch[0], resolution_status="quarantined",
                             error=f"rc={completed.returncode}")]
            middle = len(batch) // 2
            return (
                resolve_batch(bundle, batch[:middle], canonical,
                              revision_id, final_feature)
                + resolve_batch(bundle, batch[middle:], canonical,
                                revision_id, final_feature)
            )
        return [
            json.loads(line)
            for line in out_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def build(bundle: Path, database: Path, *, namespace: str,
          final_feature: str, batch_size: int = DEFAULT_BATCH) -> BuildReport:
    """Build the index for one namespace of one bundle."""
    started = time.monotonic()
    bundle = Path(bundle).resolve()
    connection = store.connect(Path(database))
    report = BuildReport(namespace=namespace, revision_id="")
    try:
        session = _open(bundle)
        try:
            revision_id = f"rev-{getattr(session, 'revision_number', 1):06d}"
            report.revision_id = revision_id
            features = [
                entry.key.object_id
                for entry in session.label_index.entries()
                if entry.retired_revision is None
                and entry.key.object_kind == "feature"
            ]
            roles = role_records(session, namespace)
            report.roles_total = len(roles)
            for role in roles:
                role["revision_id"] = revision_id

            canonical = measure_canonical(session, final_feature, revision_id)
            report.canonical_faces = len(canonical)
            for row in canonical:
                store.insert_canonical(connection, row)
            connection.commit()

            carry = [r for r in roles if r["_class"] == "carry"]
            face_level = [r for r in roles if r["_class"] == "face_level"]
            history = [r for r in roles if r["_class"] not in
                       ("carry", "face_level")]

            # History roles are never face candidates. Recorded so a reader can
            # see they were considered and why they were left out, without
            # opening a single one of them.
            for role in history:
                store.insert_role(connection, {
                    **role, "resolution_status": "not_face",
                    "resolution_method": "classified_from_key",
                })
            connection.commit()

            if carry:
                candidates = [f for f in features if f != final_feature]
                recovered, operand, scores = recover_carry(
                    session, carry, final_feature, candidates
                )
                report.carry_operand = operand
                report.carry_candidates = scores
                for role in recovered:
                    store.insert_role(connection, role)
                connection.commit()
        finally:
            session.close()

        # The only part that needs a subprocess, and the only part that can
        # fault: reading a role's TNaming attribute.
        for start in range(0, len(face_level), batch_size):
            chunk = face_level[start:start + batch_size]
            resolved = resolve_batch(
                bundle, chunk, canonical, revision_id, final_feature
            )
            for row in resolved:
                store.insert_role(connection, row)
            report.batches += 1
            connection.commit()

        counted = connection.execute(
            "SELECT resolution_status, relation_kind, COUNT(*) FROM face_roles "
            "WHERE namespace = ? GROUP BY 1, 2", (namespace,)
        ).fetchall()
        for status, kind, count in counted:
            if status == "resolved":
                report.roles_resolved += count
                report.resolved_by_kind[kind] = (
                    report.resolved_by_kind.get(kind, 0) + count
                )
            elif status == "not_face":
                report.roles_not_face += count
            elif status == "quarantined":
                report.quarantined += count
                report.roles_errored += count
            else:
                report.roles_unresolved += count
        report.roles_unresolved += report.quarantined
        store.set_meta(connection, f"build:{namespace}", report.as_dict())
        connection.commit()
    finally:
        connection.close()
    report.seconds = time.monotonic() - started
    return report


__all__ = ["BuildReport", "build", "classify", "measure_canonical",
           "recover_carry", "role_records", "DEFAULT_BATCH"]
