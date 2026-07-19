"""PersistentTopoId — stable topology identity, decoupled from B-Rep enumeration.

Rules (enforced by Pydantic validators):
  - scheme MUST be "gcad_topo_v1"
  - No runtime index allowed (face_index, edge_index)
  - No memory address or Python id() allowed
  - No random UUID allowed
"""

from __future__ import annotations

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
