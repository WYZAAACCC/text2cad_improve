"""Generic paged search over the face-evolution SQLite index."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

STRUCTURAL_ROOT = Path(__file__).resolve().parents[1]
if str(STRUCTURAL_ROOT) not in sys.path:
    sys.path.insert(0, str(STRUCTURAL_ROOT))

from face_evolution.face_index import connect


def _row_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    for key in ("label_path_json", "bbox_json", "fact_json", "metadata_json"):
        if result.get(key):
            try:
                result[key.removesuffix("_json")] = json.loads(result[key])
            except json.JSONDecodeError:
                pass
        result.pop(key, None)
    return result


def scope_summary(database: Path) -> dict:
    connection = connect(database)
    try:
        canonical_count = connection.execute(
            "SELECT COUNT(*) FROM canonical_faces"
        ).fetchone()[0]
        role_counts = Counter(
            row[0]
            for row in connection.execute(
                "SELECT namespace FROM face_roles"
            )
        )
        status_counts = Counter(
            row[0]
            for row in connection.execute(
                "SELECT resolution_status FROM face_roles"
            )
        )
        relation_counts = Counter(
            row[0]
            for row in connection.execute(
                "SELECT namespace FROM evolution_relations"
            )
        )
        source_counts = Counter(
            row[0]
            for row in connection.execute(
                "SELECT feature_id FROM source_faces"
            )
        )
        return {
            "canonical_face_count": canonical_count,
            "face_roles_by_namespace": dict(role_counts),
            "face_roles_by_status": dict(status_counts),
            "relations_by_namespace": dict(relation_counts),
            "source_faces_by_feature": dict(source_counts),
        }
    finally:
        connection.close()


def search_final_faces(
    database: Path,
    *,
    feature_id: str | None = None,
    surface_type: str | None = None,
    area_min: float | None = None,
    area_max: float | None = None,
    radial_min: float | None = None,
    radial_max: float | None = None,
    theta_min: float | None = None,
    theta_max: float | None = None,
    z_min: float | None = None,
    z_max: float | None = None,
    limit: int = 30,
    offset: int = 0,
) -> dict:
    clauses = []
    params = []
    for column, value, op in (
        ("feature_id", feature_id, "="),
        ("surface_type", surface_type, "="),
        ("area_mm2", area_min, ">="),
        ("area_mm2", area_max, "<="),
        ("radius_mm", radial_min, ">="),
        ("radius_mm", radial_max, "<="),
        ("theta_deg", theta_min, ">="),
        ("theta_deg", theta_max, "<="),
        ("z_mm", z_min, ">="),
        ("z_mm", z_max, "<="),
    ):
        if value is not None:
            clauses.append(f"{column} {op} ?")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    connection = connect(database)
    try:
        total = connection.execute(
            "SELECT COUNT(*) FROM canonical_faces" + where, params
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT * FROM canonical_faces"
            + where
            + " ORDER BY solid_index, face_index LIMIT ? OFFSET ?",
            [*params, max(1, min(limit, 200)), max(0, offset)],
        ).fetchall()
        return {
            "total": total,
            "returned": len(rows),
            "offset": offset,
            "truncated": offset + len(rows) < total,
            "faces": [_row_dict(row) for row in rows],
        }
    finally:
        connection.close()


def search_face_roles(
    database: Path,
    *,
    namespace: str | None = None,
    role_prefix: str | None = None,
    resolution_status: str | None = None,
    relation_kind: str | None = None,
    surface_type: str | None = None,
    resolved_face_id: str | None = None,
    area_min: float | None = None,
    area_max: float | None = None,
    radial_min: float | None = None,
    radial_max: float | None = None,
    theta_min: float | None = None,
    theta_max: float | None = None,
    z_min: float | None = None,
    z_max: float | None = None,
    normal_radial_min: float | None = None,
    normal_radial_max: float | None = None,
    normal_tangential_min: float | None = None,
    normal_tangential_max: float | None = None,
    normal_axial_min: float | None = None,
    normal_axial_max: float | None = None,
    limit: int = 30,
    offset: int = 0,
) -> dict:
    clauses = []
    params = []
    for column, value, op in (
        ("namespace", namespace, "="),
        ("resolution_status", resolution_status, "="),
        ("relation_kind", relation_kind, "="),
        ("surface_type", surface_type, "="),
        ("resolved_face_id", resolved_face_id, "="),
        ("area_mm2", area_min, ">="),
        ("area_mm2", area_max, "<="),
        ("radius_mm", radial_min, ">="),
        ("radius_mm", radial_max, "<="),
        ("theta_deg", theta_min, ">="),
        ("theta_deg", theta_max, "<="),
        ("z_mm", z_min, ">="),
        ("z_mm", z_max, "<="),
        ("normal_radial", normal_radial_min, ">="),
        ("normal_radial", normal_radial_max, "<="),
        ("normal_tangential", normal_tangential_min, ">="),
        ("normal_tangential", normal_tangential_max, "<="),
        ("normal_axial", normal_axial_min, ">="),
        ("normal_axial", normal_axial_max, "<="),
    ):
        if value is not None:
            clauses.append(f"{column} {op} ?")
            params.append(value)
    if role_prefix is not None:
        clauses.append("role_key LIKE ?")
        params.append(role_prefix + "%")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    connection = connect(database)
    try:
        total = connection.execute(
            "SELECT COUNT(*) FROM face_roles" + where, params
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT * FROM face_roles"
            + where
            + " ORDER BY namespace, role_key LIMIT ? OFFSET ?",
            [*params, max(1, min(limit, 200)), max(0, offset)],
        ).fetchall()
        facets = {}
        for column in (
            "namespace",
            "resolution_status",
            "relation_kind",
            "surface_type",
        ):
            facets[column] = dict(
                connection.execute(
                    f"SELECT {column}, COUNT(*) FROM face_roles"
                    + where
                    + f" GROUP BY {column}"
                    + f" ORDER BY COUNT(*) DESC",
                    params,
                ).fetchall()
            )
        return {
            "total": total,
            "returned": len(rows),
            "offset": offset,
            "truncated": offset + len(rows) < total,
            "facets": facets,
            "roles": [_row_dict(row) for row in rows],
        }
    finally:
        connection.close()


def search_source_faces(
    database: Path,
    *,
    feature_id: str | None = None,
    surface_type: str | None = None,
    area_min: float | None = None,
    area_max: float | None = None,
    radial_min: float | None = None,
    radial_max: float | None = None,
    theta_min: float | None = None,
    theta_max: float | None = None,
    z_min: float | None = None,
    z_max: float | None = None,
    limit: int = 30,
    offset: int = 0,
) -> dict:
    clauses = []
    params = []
    for column, value, op in (
        ("feature_id", feature_id, "="),
        ("surface_type", surface_type, "="),
        ("area_mm2", area_min, ">="),
        ("area_mm2", area_max, "<="),
        ("radius_mm", radial_min, ">="),
        ("radius_mm", radial_max, "<="),
        ("theta_deg", theta_min, ">="),
        ("theta_deg", theta_max, "<="),
        ("z_mm", z_min, ">="),
        ("z_mm", z_max, "<="),
    ):
        if value is not None:
            clauses.append(f"{column} {op} ?")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    connection = connect(database)
    try:
        total = connection.execute(
            "SELECT COUNT(*) FROM source_faces" + where, params
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT * FROM source_faces"
            + where
            + " ORDER BY feature_id, face_index LIMIT ? OFFSET ?",
            [*params, max(1, min(limit, 200)), max(0, offset)],
        ).fetchall()
        return {
            "total": total,
            "returned": len(rows),
            "offset": offset,
            "truncated": offset + len(rows) < total,
            "faces": [_row_dict(row) for row in rows],
        }
    finally:
        connection.close()


def source_face_for_role(database: Path, role: dict) -> dict | None:
    source_key = role.get("source_key") or ""
    feature_id = None
    index = None
    if source_key.startswith("tool_face_"):
        feature_id = "n_pattern_cutters"
        index = int(source_key.split("_", 2)[2])
    elif source_key.startswith("target_face_"):
        feature_id = "n_disc_revolve"
        index = int(source_key.split("_", 2)[2])
    if feature_id is None or index is None:
        return None
    connection = connect(database)
    try:
        row = connection.execute(
            """
            SELECT * FROM source_faces
            WHERE feature_id = ? AND face_index = ?
            """,
            (feature_id, index),
        ).fetchone()
        return None if row is None else _row_dict(row)
    finally:
        connection.close()


def roles_for_face(database: Path, canonical_face_id: str) -> list[dict]:
    connection = connect(database)
    try:
        rows = connection.execute(
            """
            SELECT * FROM face_roles
            WHERE resolved_face_id = ?
            ORDER BY relation_kind, role_key
            """,
            (canonical_face_id,),
        ).fetchall()
        return [_row_dict(row) for row in rows]
    finally:
        connection.close()


def relations_for_role(database: Path, role_id: str) -> list[dict]:
    connection = connect(database)
    try:
        role = connection.execute(
            "SELECT * FROM face_roles WHERE role_id = ?", (role_id,)
        ).fetchone()
        if role is None:
            return []
        rows = connection.execute(
            """
            SELECT * FROM evolution_relations
            WHERE namespace = ? AND source_key = ?
            ORDER BY relation_key
            """,
            (role["namespace"], role["source_key"]),
        ).fetchall()
        return [_row_dict(row) for row in rows]
    finally:
        connection.close()


def trace_role(database: Path, role_id: str, limit: int = 50) -> dict:
    connection = connect(database)
    try:
        role = connection.execute(
            "SELECT * FROM face_roles WHERE role_id = ?", (role_id,)
        ).fetchone()
        if role is None:
            return {"role_id": role_id, "relations": [], "siblings": []}
        relations = connection.execute(
            """
            SELECT * FROM evolution_relations
            WHERE namespace = ? AND source_key = ?
            ORDER BY relation_key LIMIT ?
            """,
            (role["namespace"], role["source_key"], max(1, min(limit, 200))),
        ).fetchall()
        siblings = connection.execute(
            """
            SELECT * FROM face_roles
            WHERE namespace = ? AND source_key = ? AND role_id != ?
            ORDER BY role_key LIMIT ?
            """,
            (
                role["namespace"],
                role["source_key"],
                role_id,
                max(1, min(limit, 200)),
            ),
        ).fetchall()
        return {
            "role": _row_dict(role),
            "relations": [_row_dict(row) for row in relations],
            "siblings": [_row_dict(row) for row in siblings],
            "source_face": source_face_for_role(
                database, _row_dict(role)
            ),
        }
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scopes")
    faces = sub.add_parser("faces")
    faces.add_argument("--feature")
    faces.add_argument("--surface-type")
    faces.add_argument("--radial-min", type=float)
    faces.add_argument("--radial-max", type=float)
    faces.add_argument("--theta-min", type=float)
    faces.add_argument("--theta-max", type=float)
    faces.add_argument("--limit", type=int, default=30)
    faces.add_argument("--offset", type=int, default=0)
    roles = sub.add_parser("roles")
    roles.add_argument("--namespace")
    roles.add_argument("--role-prefix")
    roles.add_argument("--resolution-status")
    roles.add_argument("--relation-kind")
    roles.add_argument("--surface-type")
    roles.add_argument("--resolved-face-id")
    roles.add_argument("--limit", type=int, default=30)
    roles.add_argument("--offset", type=int, default=0)
    role_faces = sub.add_parser("roles-for-face")
    role_faces.add_argument("canonical_face_id")
    role_relations = sub.add_parser("relations-for-role")
    role_relations.add_argument("role_id")
    role_trace = sub.add_parser("trace-role")
    role_trace.add_argument("role_id")
    source = sub.add_parser("source-faces")
    source.add_argument("--feature")
    source.add_argument("--surface-type")
    source.add_argument("--radial-min", type=float)
    source.add_argument("--radial-max", type=float)
    source.add_argument("--theta-min", type=float)
    source.add_argument("--theta-max", type=float)
    source.add_argument("--limit", type=int, default=30)
    source.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    if args.command == "scopes":
        result = scope_summary(args.database)
    elif args.command == "faces":
        result = search_final_faces(
            args.database,
            feature_id=args.feature,
            surface_type=args.surface_type,
            radial_min=args.radial_min,
            radial_max=args.radial_max,
            theta_min=args.theta_min,
            theta_max=args.theta_max,
            limit=args.limit,
            offset=args.offset,
        )
    elif args.command == "roles":
        result = search_face_roles(
            args.database,
            namespace=args.namespace,
            role_prefix=args.role_prefix,
            resolution_status=args.resolution_status,
            relation_kind=args.relation_kind,
            surface_type=args.surface_type,
            resolved_face_id=args.resolved_face_id,
            limit=args.limit,
            offset=args.offset,
        )
    elif args.command == "roles-for-face":
        result = roles_for_face(args.database, args.canonical_face_id)
    elif args.command == "relations-for-role":
        result = relations_for_role(args.database, args.role_id)
    elif args.command == "source-faces":
        result = search_source_faces(
            args.database,
            feature_id=args.feature,
            surface_type=args.surface_type,
            radial_min=args.radial_min,
            radial_max=args.radial_max,
            theta_min=args.theta_min,
            theta_max=args.theta_max,
            limit=args.limit,
            offset=args.offset,
        )
    else:
        result = trace_role(args.database, args.role_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
