"""The face-evolution index: schema, connection, and the inserts.

The index answers one question - given a role recorded in the CAD document,
which face of the finished part is it? - and it answers it as a lookup rather
than by re-reading the document, because reading the document is where the
cost and the crashes are.

Two tables carry the answer:

  `canonical_faces`  the finished part's faces, with the same measurements the
                     face-finding tools report. Keyed by revision, feature,
                     solid and face index - an identity within one revision.
  `face_roles`       one row per role recorded in the document, saying what it
                     is and which canonical face it resolved to (or why it
                     could not be resolved).

The separation matters. A role is the *persistent* identity - it survives a
design revision - and a canonical face is the *current* identity. Keeping them
in one table would invite reading a face index as though it meant the same
thing next revision.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
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
    fact_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_face_roles_resolved
    ON face_roles(resolved_face_id);
CREATE INDEX IF NOT EXISTS idx_face_roles_namespace
    ON face_roles(namespace, relation_kind);
CREATE INDEX IF NOT EXISTS idx_canonical_geometry
    ON canonical_faces(feature_id, radius_mm, surface_type);
"""

CANONICAL_COLUMNS = (
    "canonical_face_id", "revision_id", "feature_id", "solid_index",
    "face_index", "surface_type", "area_mm2", "centroid_x", "centroid_y",
    "centroid_z", "radius_mm", "theta_deg", "z_mm", "normal_x", "normal_y",
    "normal_z", "normal_radial", "normal_tangential", "normal_axial",
    "bbox_json", "fact_json",
)

ROLE_COLUMNS = (
    "role_id", "revision_id", "namespace", "feature_id", "role_key",
    "role_tag", "label_path_json", "created_revision", "relation_kind",
    "source_key", "operation_id", "resolution_status", "resolution_method",
    "resolved_face_id", "surface_type", "area_mm2", "centroid_x", "centroid_y",
    "centroid_z", "radius_mm", "theta_deg", "z_mm", "normal_x", "normal_y",
    "normal_z", "normal_radial", "normal_tangential", "normal_axial",
    "bbox_json", "error", "fact_json",
)


def connect(path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(SCHEMA)
    return connection


def insert_canonical(connection, row: dict) -> None:
    values = [row.get(name) for name in CANONICAL_COLUMNS]
    connection.execute(
        f"INSERT OR REPLACE INTO canonical_faces "
        f"({','.join(CANONICAL_COLUMNS)}) "
        f"VALUES ({','.join('?' * len(CANONICAL_COLUMNS))})",
        values,
    )


def insert_role(connection, row: dict) -> None:
    values = [row.get(name) for name in ROLE_COLUMNS]
    connection.execute(
        f"INSERT OR REPLACE INTO face_roles "
        f"({','.join(ROLE_COLUMNS)}) "
        f"VALUES ({','.join('?' * len(ROLE_COLUMNS))})",
        values,
    )


def set_meta(connection, key: str, value) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
        (key, json.dumps(value, ensure_ascii=False)),
    )


def get_meta(connection, key: str, default=None):
    row = connection.execute(
        "SELECT value FROM index_meta WHERE key = ?", (key,)
    ).fetchone()
    return default if row is None else json.loads(row["value"])


def face_id(revision_id: str, solid_index: int, face_index: int) -> str:
    return f"{revision_id}:solid:{solid_index}:face:{face_index}"


def index_path(job_dir: Path) -> Path:
    return Path(job_dir) / "model" / "face_evolution.sqlite"


def has_namespace(database, namespace: str) -> bool:
    """Whether a feature has already been indexed in this file."""
    path = Path(database)
    if not path.exists():
        return False
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(
            "SELECT 1 FROM face_roles WHERE namespace = ? LIMIT 1",
            (namespace,),
        ).fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        connection.close()


def revision_of(database) -> str:
    """Which revision the index holds, or empty when it holds none.

    Read rather than assumed: a face id is only meaningful inside one
    revision, so a caller that guessed the revision would be addressing faces
    by a name that means something else in the next one.
    """
    path = Path(database)
    if not path.exists():
        return ""
    connection = sqlite3.connect(str(path))
    try:
        row = connection.execute(
            "SELECT revision_id FROM canonical_faces LIMIT 1"
        ).fetchone()
        return "" if row is None else str(row[0])
    except sqlite3.Error:
        return ""
    finally:
        connection.close()


__all__ = [
    "connect", "face_id", "get_meta", "has_namespace", "index_path",
    "insert_canonical", "insert_role", "revision_of", "set_meta",
    "CANONICAL_COLUMNS", "ROLE_COLUMNS", "SCHEMA",
]
