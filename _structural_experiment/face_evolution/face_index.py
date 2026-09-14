"""SQLite storage for final faces and their persistent role history."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA_VERSION = "face_evolution_v1"


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def initialize_index(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS index_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS canonical_faces (
            canonical_face_id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL,
            feature_id TEXT NOT NULL,
            solid_index INTEGER NOT NULL,
            face_index INTEGER NOT NULL,
            surface_type TEXT NOT NULL,
            area_mm2 REAL NOT NULL,
            centroid_x REAL NOT NULL,
            centroid_y REAL NOT NULL,
            centroid_z REAL NOT NULL,
            radius_mm REAL NOT NULL,
            theta_deg REAL NOT NULL,
            z_mm REAL NOT NULL,
            normal_x REAL,
            normal_y REAL,
            normal_z REAL,
            normal_radial REAL,
            normal_tangential REAL,
            normal_axial REAL,
            bbox_json TEXT,
            fact_json TEXT NOT NULL,
            UNIQUE(revision_id, feature_id, solid_index, face_index)
        );

        CREATE TABLE IF NOT EXISTS face_roles (
            role_id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL,
            namespace TEXT NOT NULL,
            feature_id TEXT NOT NULL,
            role_key TEXT NOT NULL,
            role_tag INTEGER NOT NULL,
            label_path_json TEXT NOT NULL,
            created_revision INTEGER,
            relation_kind TEXT NOT NULL,
            source_key TEXT,
            operation_id TEXT,
            resolution_status TEXT NOT NULL,
            resolution_method TEXT,
            resolved_face_id TEXT,
            surface_type TEXT,
            area_mm2 REAL,
            centroid_x REAL,
            centroid_y REAL,
            centroid_z REAL,
            radius_mm REAL,
            theta_deg REAL,
            z_mm REAL,
            normal_x REAL,
            normal_y REAL,
            normal_z REAL,
            normal_radial REAL,
            normal_tangential REAL,
            normal_axial REAL,
            bbox_json TEXT,
            error TEXT,
            fact_json TEXT,
            FOREIGN KEY(resolved_face_id) REFERENCES canonical_faces(canonical_face_id)
        );

        CREATE TABLE IF NOT EXISTS evolution_relations (
            relation_id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL,
            namespace TEXT NOT NULL,
            feature_id TEXT NOT NULL,
            relation_key TEXT NOT NULL,
            relation_tag INTEGER NOT NULL,
            label_path_json TEXT NOT NULL,
            source_key TEXT,
            evolution_kind TEXT,
            relation_role TEXT,
            metadata_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS source_faces (
            source_face_id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL,
            feature_id TEXT NOT NULL,
            solid_index INTEGER NOT NULL,
            face_index INTEGER NOT NULL,
            surface_type TEXT NOT NULL,
            area_mm2 REAL NOT NULL,
            centroid_x REAL NOT NULL,
            centroid_y REAL NOT NULL,
            centroid_z REAL NOT NULL,
            radius_mm REAL NOT NULL,
            theta_deg REAL NOT NULL,
            z_mm REAL NOT NULL,
            normal_x REAL,
            normal_y REAL,
            normal_z REAL,
            normal_radial REAL,
            normal_tangential REAL,
            normal_axial REAL,
            bbox_json TEXT,
            fact_json TEXT NOT NULL,
            UNIQUE(revision_id, feature_id, solid_index, face_index)
        );

        CREATE INDEX IF NOT EXISTS idx_face_roles_namespace
            ON face_roles(namespace);
        CREATE INDEX IF NOT EXISTS idx_face_roles_resolved
            ON face_roles(resolved_face_id);
        CREATE INDEX IF NOT EXISTS idx_face_roles_surface_type
            ON face_roles(surface_type);
        CREATE INDEX IF NOT EXISTS idx_face_roles_geometry
            ON face_roles(area_mm2, radius_mm, theta_deg, z_mm);
        CREATE INDEX IF NOT EXISTS idx_relation_namespace
            ON evolution_relations(namespace);
        CREATE INDEX IF NOT EXISTS idx_relation_source
            ON evolution_relations(source_key);
        CREATE INDEX IF NOT EXISTS idx_source_faces_geometry
            ON source_faces(area_mm2, radius_mm, theta_deg, z_mm);
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO index_meta(key, value) VALUES(?, ?)",
        ("schema_version", SCHEMA_VERSION),
    )
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(face_roles)")
    }
    if "resolution_method" not in columns:
        connection.execute(
            "ALTER TABLE face_roles ADD COLUMN resolution_method TEXT"
        )
    connection.commit()


def set_meta(connection: sqlite3.Connection, key: str, value) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO index_meta(key, value) VALUES(?, ?)",
        (key, json.dumps(value, ensure_ascii=False, sort_keys=True)),
    )
    connection.commit()


def get_meta(connection: sqlite3.Connection, key: str, default=None):
    row = connection.execute(
        "SELECT value FROM index_meta WHERE key = ?", (key,)
    ).fetchone()
    return default if row is None else json.loads(row["value"])


def insert_canonical_face(connection: sqlite3.Connection, row: dict) -> None:
    facts = row.get("fact_json")
    if facts is None:
        facts = json.dumps(row, ensure_ascii=False, sort_keys=True)
    centroid = row.get("centroid_mm") or [0.0, 0.0, 0.0]
    normal = row.get("normal_xyz") or [None, None, None]
    normal_cyl = row.get("normal_cylindrical") or {}
    connection.execute(
        """
        INSERT OR REPLACE INTO canonical_faces(
            canonical_face_id, revision_id, feature_id, solid_index, face_index,
            surface_type, area_mm2, centroid_x, centroid_y, centroid_z,
            radius_mm, theta_deg, z_mm, normal_x, normal_y, normal_z,
            normal_radial, normal_tangential, normal_axial, bbox_json, fact_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["canonical_face_id"],
            row["revision_id"],
            row["feature_id"],
            int(row["solid_index"]),
            int(row["face_index"]),
            row["surface_type"],
            float(row["area_mm2"]),
            float(centroid[0]),
            float(centroid[1]),
            float(centroid[2]),
            float(row.get("radius_mm", 0.0)),
            float(row.get("theta_deg", 0.0)),
            float(row.get("z_mm", 0.0)),
            None if normal[0] is None else float(normal[0]),
            None if normal[1] is None else float(normal[1]),
            None if normal[2] is None else float(normal[2]),
            normal_cyl.get("radial"),
            normal_cyl.get("tangential"),
            normal_cyl.get("axial"),
            json.dumps(row.get("bbox_mm"), ensure_ascii=False),
            facts,
        ),
    )


def insert_face_role(connection: sqlite3.Connection, row: dict) -> None:
    facts = row.get("fact_json")
    if facts is None:
        facts = json.dumps(row, ensure_ascii=False, sort_keys=True)
    centroid = row.get("centroid_mm") or [None, None, None]
    normal = row.get("normal_xyz") or [None, None, None]
    normal_cyl = row.get("normal_cylindrical") or {}
    connection.execute(
        """
        INSERT OR REPLACE INTO face_roles(
            role_id, revision_id, namespace, feature_id, role_key, role_tag,
            label_path_json, created_revision, relation_kind, source_key,
            operation_id, resolution_status, resolution_method,
            resolved_face_id, surface_type,
            area_mm2, centroid_x, centroid_y, centroid_z, radius_mm, theta_deg,
            z_mm, normal_x, normal_y, normal_z, normal_radial,
            normal_tangential, normal_axial, bbox_json, error, fact_json
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            row["role_id"],
            row["revision_id"],
            row["namespace"],
            row["feature_id"],
            row["role_key"],
            int(row["role_tag"]),
            json.dumps(row.get("label_path", []), ensure_ascii=False),
            row.get("created_revision"),
            row["relation_kind"],
            row.get("source_key"),
            row.get("operation_id"),
            row["resolution_status"],
            row.get("resolution_method"),
            row.get("resolved_face_id"),
            row.get("surface_type"),
            row.get("area_mm2"),
            centroid[0],
            centroid[1],
            centroid[2],
            row.get("radius_mm"),
            row.get("theta_deg"),
            row.get("z_mm"),
            normal[0],
            normal[1],
            normal[2],
            normal_cyl.get("radial"),
            normal_cyl.get("tangential"),
            normal_cyl.get("axial"),
            json.dumps(row.get("bbox_mm"), ensure_ascii=False),
            row.get("error"),
            facts,
        ),
    )


def insert_relation(connection: sqlite3.Connection, row: dict) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO evolution_relations(
            relation_id, revision_id, namespace, feature_id, relation_key,
            relation_tag, label_path_json, source_key, evolution_kind,
            relation_role, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["relation_id"],
            row["revision_id"],
            row["namespace"],
            row["feature_id"],
            row["relation_key"],
            int(row["relation_tag"]),
            json.dumps(row.get("label_path", []), ensure_ascii=False),
            row.get("source_key"),
            row.get("evolution_kind"),
            row.get("relation_role"),
            json.dumps(row, ensure_ascii=False, sort_keys=True),
        ),
    )


def insert_source_face(connection: sqlite3.Connection, row: dict) -> None:
    facts = row.get("fact_json")
    if facts is None:
        facts = json.dumps(row, ensure_ascii=False, sort_keys=True)
    centroid = row.get("centroid_mm") or [0.0, 0.0, 0.0]
    normal = row.get("normal_xyz") or [None, None, None]
    normal_cyl = row.get("normal_cylindrical") or {}
    connection.execute(
        """
        INSERT OR REPLACE INTO source_faces(
            source_face_id, revision_id, feature_id, solid_index, face_index,
            surface_type, area_mm2, centroid_x, centroid_y, centroid_z,
            radius_mm, theta_deg, z_mm, normal_x, normal_y, normal_z,
            normal_radial, normal_tangential, normal_axial, bbox_json, fact_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["source_face_id"],
            row["revision_id"],
            row["feature_id"],
            int(row["solid_index"]),
            int(row["face_index"]),
            row["surface_type"],
            float(row["area_mm2"]),
            float(centroid[0]),
            float(centroid[1]),
            float(centroid[2]),
            float(row.get("radius_mm", 0.0)),
            float(row.get("theta_deg", 0.0)),
            float(row.get("z_mm", 0.0)),
            None if normal[0] is None else float(normal[0]),
            None if normal[1] is None else float(normal[1]),
            None if normal[2] is None else float(normal[2]),
            normal_cyl.get("radial"),
            normal_cyl.get("tangential"),
            normal_cyl.get("axial"),
            json.dumps(row.get("bbox_mm"), ensure_ascii=False),
            facts,
        ),
    )
