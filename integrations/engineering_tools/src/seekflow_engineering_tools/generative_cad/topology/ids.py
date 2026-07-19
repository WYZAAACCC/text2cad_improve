"""PersistentTopoId — stable topology identity, decoupled from B-Rep enumeration.

V3 upgrade: TopologyIdentityDescriptorV3 is the canonical identity model.
v1 (PersistentTopoId) and v2 (PersistentTopoIdV2) are DEPRECATED —
  reader preserved for migration, writer only produces v3.

Rules (enforced by Pydantic validators):
  - No runtime index allowed (face_index, edge_index) in identity descriptor
  - No memory address or Python id() allowed
  - No random UUID allowed
  - semantic_path is a structured tuple of tokens, not a free-form string
"""

from __future__ import annotations

import base64
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class PersistentTopoId(BaseModel):
    """[DEPRECATED] Stable topology identity v1 — use TopologyIdentityDescriptorV3.

    Serialized form:
      gct:v1:<document>:<component>:<root-node>:<producer-node>:face:<role>:<branch>

    Deprecated because:
      - document_id truncated to 12 chars (collision risk)
      - No field escaping — colon in role breaks parsing
      - Contains producer_node_id (changes on node rename)
      - v3 replaces this with content-hash-based key and structured descriptor

    Human-readable alias:
      component.disk/feature.center_bore/wall
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scheme: Literal["gcad_topo_v1"] = "gcad_topo_v1"

    document_id: str
    component_id: str

    lineage_root_node_id: str
    producer_node_id: str

    entity_type: Literal["solid", "shell", "face", "wire", "edge", "vertex"]

    semantic_role: str
    branch_token: str | None = None

    # ── Validation ──

    @field_validator("semantic_role")
    @classmethod
    def _no_runtime_index(cls, v: str) -> str:
        """Reject purely numeric semantic roles — those are runtime indices."""
        stripped = v.strip()
        if stripped.isdigit():
            raise ValueError(
                f"semantic_role must not be a raw index: {v!r}. "
                f"Use descriptive names like 'top', 'hole_wall', 'side_face', etc."
            )
        if stripped.lower() in ("face", "edge", "vertex"):
            raise ValueError(
                f"semantic_role must not be a bare entity type: {v!r}. "
                f"Use a descriptive name like 'face/top', 'edge/rim', etc."
            )
        return v

    # ── Serialization ──

    def to_compact(self) -> str:
        """gct:v1:<document>:<component>:<root>:<producer>:<type>:<role>[:<branch>]"""
        parts = [
            "gct", "v1",
            self.document_id[:12],
            self.component_id,
            self.lineage_root_node_id,
            self.producer_node_id,
            self.entity_type,
            self.semantic_role,
        ]
        if self.branch_token:
            parts.append(self.branch_token)
        return ":".join(parts)

    @classmethod
    def from_compact(cls, s: str) -> "PersistentTopoId":
        """Parse a compact string back to PersistentTopoId."""
        parts = s.split(":")
        if len(parts) < 8 or parts[0] != "gct" or parts[1] != "v1":
            raise ValueError(
                f"Invalid compact PersistentTopoId: {s!r}. "
                f"Expected: gct:v1:<doc>:<comp>:<root>:<producer>:<type>:<role>"
            )
        return cls(
            document_id=parts[2],
            component_id=parts[3],
            lineage_root_node_id=parts[4],
            producer_node_id=parts[5],
            entity_type=parts[6],  # type: ignore[arg-type]
            semantic_role=parts[7],
            branch_token=parts[8] if len(parts) > 8 else None,
        )

    def to_sha256(self) -> str:
        """Deterministic hash for compact storage and comparison."""
        payload = self.model_dump_json(exclude={"scheme"})
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()

    def to_alias(self) -> str:
        """Human-readable alias: component.<comp>/feature.<producer>/<role>"""
        base = f"component.{self.component_id}/feature.{self.producer_node_id}/{self.semantic_role}"
        if self.branch_token:
            base += f"/{self.branch_token}"
        return base


# ═══════════════════════════════════════════════════════════════════════════════
# PersistentTopoId v2 — content-hash-keyed, no truncation
# ═══════════════════════════════════════════════════════════════════════════════


class PersistentTopoIdV2(BaseModel):
    """[DEPRECATED] Stable topology identity v2 — use TopologyIdentityDescriptorV3.

    Scheme: gcad_topo_v2
    Authoritative key: gct2_<base64url(sha256(canonical_json))>

    Deprecated because:
      - Hash includes mutable fields (document_id, producer_node_id) — node rename
        or document clone changes the key, violating I-03.
      - Descriptor is not preserved in the record — once hashed, there is no
        way to recover the identity description from just the key.
      - v3 fixes both: descriptor saved in record/sidecar; document_lineage_id
        and feature_stable_id replace document_id + producer_node_id.

    The key alone is sufficient to uniquely identify the entity.
    All structured fields are preserved in the record/sidecar for
    human readability, lineage tracing, and debugging.

    Differences from v1:
      - Authoritative key is a content hash, NOT a colon-delimited string
      - No truncation of any fields
      - No colon-escaping issues (keys use base64url alphabet only)
      - Full structured payload preserved in sidecar
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scheme: Literal["gcad_topo_v2"] = "gcad_topo_v2"

    document_id: str
    component_id: str
    lineage_root_node_id: str
    producer_node_id: str
    entity_type: Literal["solid", "shell", "face", "wire", "edge", "vertex"]
    semantic_role: str
    branch_token: str | None = None

    # ── Validation (same rules as v1) ──

    @field_validator("semantic_role")
    @classmethod
    def _no_runtime_index(cls, v: str) -> str:
        """Reject purely numeric semantic roles — those are runtime indices."""
        stripped = v.strip()
        if stripped.isdigit():
            raise ValueError(
                f"semantic_role must not be a raw index: {v!r}. "
                f"Use descriptive names like 'top', 'hole_wall', 'side/+x', etc."
            )
        if stripped.lower() in ("face", "edge", "vertex"):
            raise ValueError(
                f"semantic_role must not be a bare entity type: {v!r}. "
                f"Use a descriptive name like 'face/top', 'edge/rim', etc."
            )
        return v

    # ── Authoritative key ──

    def to_key(self) -> str:
        """Generate the authoritative compact key: gct2_<base64url(sha256)>.

        This is the canonical string form used as persistent_id in the registry.
        It is content-addressed — any change to any field produces a new key.
        """
        payload = self.model_dump_json(exclude={"scheme"})
        digest = hashlib.sha256(payload.encode()).digest()
        b64 = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return f"gct2_{b64}"

    # ── Human-readable alias ──

    def to_alias(self) -> str:
        """Human-readable alias: component.<comp>/feature.<producer>/<role>"""
        base = f"component.{self.component_id}/feature.{self.producer_node_id}/{self.semantic_role}"
        if self.branch_token:
            base += f"/{self.branch_token}"
        return base

    # ── Full descriptor (for logging / sidecar, not as key) ──

    def to_descriptor(self) -> str:
        """Full human-readable descriptor with all fields (no truncation).

        Uses '|' as separator to avoid colon-collision issues.
        For debugging and logging only — NOT for use as persistent_id.
        """
        parts = [
            f"gcad_topo_v2",
            f"doc={self.document_id}",
            f"comp={self.component_id}",
            f"prod={self.producer_node_id}",
            f"type={self.entity_type}",
            f"role={self.semantic_role}",
        ]
        if self.branch_token:
            parts.append(f"branch={self.branch_token}")
        return "|".join(parts)


def make_persistent_id_v2(
    document_id: str,
    component_id: str,
    producer_node_id: str,
    entity_type: Literal["solid", "shell", "face", "wire", "edge", "vertex"],
    semantic_role: str,
    branch_token: str | None = None,
    *,
    lineage_root_node_id: str | None = None,
) -> str:
    """[DEPRECATED] Create a PersistentTopoIdV2 and return its authoritative key.

    Use make_persistent_id_v3() instead. v2 keys are content-hash-based but
    include mutable fields (document_id, producer_node_id) in the hash payload.
    v3 fixes this by using document_lineage_id + feature_stable_id instead.
    """
    pid = PersistentTopoIdV2(
        document_id=document_id,
        component_id=component_id,
        lineage_root_node_id=lineage_root_node_id or producer_node_id,
        producer_node_id=producer_node_id,
        entity_type=entity_type,
        semantic_role=semantic_role,
        branch_token=branch_token,
    )
    return pid.to_key()


# ═══════════════════════════════════════════════════════════════════════════════
# PersistentTopoId V3 — canonical identity model
# ═══════════════════════════════════════════════════════════════════════════════


# ── Semantic path token validation ──

def _validate_semantic_path_token(token: str) -> None:
    """Validate a single semantic_path token.

    Rejects:
      - Pure numeric tokens (runtime indices like '0', '3', '12')
      - Tokens containing ordinal index patterns (side_face_3, lateral_2)
      - Bare entity types ('face', 'edge', 'vertex')
      - Empty or whitespace-only tokens
    """
    if not token or not token.strip():
        raise ValueError(f"semantic_path token must not be empty")
    stripped = token.strip()
    if stripped.isdigit():
        raise ValueError(
            f"semantic_path token must not be a raw index: {token!r}. "
            f"Use descriptive names like 'cap', 'start', 'from_edge_left'."
        )
    if stripped.lower() in ("face", "edge", "vertex", "solid", "shell", "wire"):
        raise ValueError(
            f"semantic_path token must not be a bare entity type: {token!r}. "
            f"Use a descriptive name like 'cap', 'wall', 'rim'."
        )
    # Reject patterns like face_3, side_face_3, edge_12, lateral_2
    import re
    ordinal_pattern = re.compile(
        r"^.*(face|edge|vertex|side|lateral|top|bottom|front|back|left|right)_\d+$",
        re.IGNORECASE,
    )
    if ordinal_pattern.match(stripped):
        raise ValueError(
            f"semantic_path token must not contain ordinal index: {token!r}. "
            f"Tokens like 'side_face_3', 'lateral_2' indicate runtime "
            f"enumeration order, not stable semantic identity."
        )


class TopologyIdentityDescriptorV3(BaseModel):
    """V3 persistent topology identity descriptor — the canonical identity model.

    Key design principles (V3 invariants I-01, I-02, I-03):
      - Identity depends only on stable features, NOT on mutable runtime state.
      - document_lineage_id is the stable document lineage identifier.
      - document_revision_id (if any) does NOT enter the identity key.
      - feature_stable_id replaces producer_node_id in the identity key.
      - producer_node_id is provenance only — not part of long-term identity.
      - semantic_path is a structured tuple of tokens, not a free-form string.
      - branch_key is only set when a single source generates multiple results.

    Authoritative key: gct3_<base64url(sha256(canonical_json))>
    The full descriptor is saved in TopologyEntityRecord.identity_descriptor
    for recoverability (v2's key-irreversibility defect is fixed).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scheme: Literal["gcad_topo_v3"] = "gcad_topo_v3"

    document_lineage_id: str
    component_stable_id: str
    feature_stable_id: str
    entity_type: Literal["solid", "shell", "face", "wire", "edge", "vertex"]
    semantic_path: tuple[str, ...]
    source_entity_keys: tuple[str, ...] = ()
    branch_key: str | None = None
    algorithm_version: str = "3.0.0"

    # ── Validation ──

    @field_validator("semantic_path")
    @classmethod
    def _validate_semantic_path(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) == 0:
            raise ValueError("semantic_path must have at least one token")
        for token in v:
            _validate_semantic_path_token(token)
        return v

    # ── Authoritative key ──

    def to_key(self) -> str:
        """Generate the authoritative compact key: gct3_<base64url(sha256)>.

        The key is computed from a canonical JSON representation of all
        identity-relevant fields. Fields that are NOT identity-relevant
        (document_revision_id, producer_node_id) are excluded from the payload.

        Uses Pydantic's model_dump_json() for stable field ordering,
        then computes SHA-256 and encodes as base64url (no padding).
        """
        payload = self.model_dump_json(exclude={"scheme"})
        digest = hashlib.sha256(payload.encode()).digest()
        b64 = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return f"gct3_{b64}"

    # ── Descriptor ──

    def to_descriptor(self) -> str:
        """Full human-readable descriptor using '|' separator.

        For debugging and sidecar logging. The structured fields are
        preserved in the record for full recoverability.
        """
        parts = [
            "gcad_topo_v3",
            f"lineage={self.document_lineage_id}",
            f"comp={self.component_stable_id}",
            f"feat={self.feature_stable_id}",
            f"type={self.entity_type}",
            f"path={'/'.join(self.semantic_path)}",
        ]
        if self.source_entity_keys:
            parts.append(f"sources={','.join(self.source_entity_keys[:3])}"
                         f"{'...' if len(self.source_entity_keys) > 3 else ''}")
        if self.branch_key:
            parts.append(f"branch={self.branch_key}")
        return "|".join(parts)

    @classmethod
    def from_descriptor_dict(cls, data: dict) -> "TopologyIdentityDescriptorV3":
        """Reconstruct from a sidecar-stored descriptor dict.

        This enables full recoverability of identity information from
        the sidecar — v3's key advantage over v2.
        """
        return cls(**data)


# ── V3 factory function ──


def make_persistent_id_v3(
    document_lineage_id: str,
    component_stable_id: str,
    feature_stable_id: str,
    entity_type: Literal["solid", "shell", "face", "wire", "edge", "vertex"],
    semantic_path: tuple[str, ...],
    *,
    source_entity_keys: tuple[str, ...] = (),
    branch_key: str | None = None,
    algorithm_version: str = "3.0.0",
) -> tuple[str, TopologyIdentityDescriptorV3]:
    """Create a V3 persistent topology ID.

    Returns:
        (key_string, descriptor) — key is the gct3_<hash> string;
        descriptor is the full structured object for storage in
        TopologyEntityRecord.identity_descriptor.

    Example:
        key, desc = make_persistent_id_v3(
            document_lineage_id="doc-1",
            component_stable_id="disk",
            feature_stable_id="revolve_main",
            entity_type="face",
            semantic_path=("revolved", "from", "edge_left"),
        )
        # key: "gct3_<43-char-base64url>"
        # desc: TopologyIdentityDescriptorV3 with all fields
    """
    desc = TopologyIdentityDescriptorV3(
        document_lineage_id=document_lineage_id,
        component_stable_id=component_stable_id,
        feature_stable_id=feature_stable_id,
        entity_type=entity_type,
        semantic_path=semantic_path,
        source_entity_keys=source_entity_keys,
        branch_key=branch_key,
        algorithm_version=algorithm_version,
    )
    return desc.to_key(), desc


# ── V1/V2/V3 migration reader ──

LEGACY_V1_MARKER = "legacy_unverified"
LEGACY_V2_IRREVERSIBLE = "v2_irreversible_no_descriptor"


def parse_persistent_id_key(key: str) -> dict:
    """Parse any PID key string (v1/v2/v3) and return version + metadata.

    Does NOT attempt to extract identity fields from v1/v2 keys.
    For v2/v3: the key is an opaque hash — the descriptor must come
    from the sidecar or TopologyEntityRecord.identity_descriptor.

    Returns:
        dict with at minimum {"version": "v1"|"v2"|"v3", "key": key}.
        For v1: adds {"legacy_status": "legacy_unverified"}.
        For v2: adds {"legacy_status": "v2_irreversible_no_descriptor"}.
        For unknown format: {"version": "unknown", "key": key}.
    """
    if not isinstance(key, str) or not key:
        return {"version": "unknown", "key": str(key)}

    if key.startswith("gct3_"):
        return {"version": "v3", "key": key, "scheme": "gcad_topo_v3"}
    if key.startswith("gct2_"):
        return {
            "version": "v2", "key": key, "scheme": "gcad_topo_v2",
            "legacy_status": LEGACY_V2_IRREVERSIBLE,
        }
    if key.startswith("gct:v1:") or key.startswith("gct:v1"):
        return {
            "version": "v1", "key": key, "scheme": "gcad_topo_v1",
            "legacy_status": LEGACY_V1_MARKER,
        }
    return {"version": "unknown", "key": key}
