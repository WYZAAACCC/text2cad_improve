"""PersistentTopoId — stable topology identity, decoupled from B-Rep enumeration.

Rules (enforced by Pydantic validators):
  - scheme MUST be "gcad_topo_v1"
  - No runtime index allowed (face_index, edge_index)
  - No memory address or Python id() allowed
  - No random UUID allowed
"""

from __future__ import annotations

import base64
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class PersistentTopoId(BaseModel):
    """Stable topology identity — survives rebuild, parameter change, feature insertion.

    Serialized form:
      gct:v1:<document>:<component>:<root-node>:<producer-node>:face:<role>:<branch>

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
    """Stable topology identity v2 — content-hash-keyed, no truncation.

    Scheme: gcad_topo_v2
    Authoritative key: gct2_<base64url(sha256(canonical_json))>

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
    """Convenience: create a PersistentTopoIdV2 and return its authoritative key."""
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
