"""CAD topology adapters — bridge PersistentTopoId to SolidWorks/NX/STEP.

Phase 7: interface contracts for commercial CAD topology mapping.
All adapters are pure Python — actual COM/NXOpen/OCP calls are
delegated to the respective bridge modules (solidworks/, nx/).

Architecture:
  G-CAD TopologyRegistry (sidecar)
      │
      ├── TopologyStepExporter  →  STEP AP242/XCAF with face names
      ├── SolidWorksTopologyAdapter  →  SW attribute ↔ PersistentTopoId
      └── NXTopologyAdapter  →  NX user attribute ↔ PersistentTopoId
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from pathlib import Path
    from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry


# ═══════════════════════════════════════════════════════════════════════════════
# Cross-backend topology proof
# ═══════════════════════════════════════════════════════════════════════════════


class CrossBackendTopologyProof(BaseModel):
    """Evidence that topology identities survived a backend transition.

    Records the mapping from G-CAD PersistentTopoId to the backend-native
    entity identifier (SW attribute, NX journal ID, STEP face name).
    """

    model_config = ConfigDict(extra="forbid")

    source_backend: str = Field(description="'gcad_cadquery' — the canonical source")
    target_backend: str = Field(description="'solidworks2025' | 'nx12' | 'step'")

    topology_schema_version: str = "gcad_topology_v1"
    topology_sidecar_sha256: str = ""

    # {PersistentTopoId: backend_entity_id}
    entity_mapping: dict[str, str] = Field(default_factory=dict)

    # Entities that could not be matched in the target backend
    unmatched_ids: list[str] = Field(default_factory=list)

    # Entities that were matched with low confidence
    low_confidence_ids: list[str] = Field(default_factory=list)

    ok: bool = False
    match_rate: float = 0.0
    issues: list[dict] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# TopologyStepExporter — STEP export with topology names
# ═══════════════════════════════════════════════════════════════════════════════


class TopologyStepExporter:
    """Export STEP with embedded topology semantic names.

    Phase 7: Uses topology sidecar as the authoritative identity record.
    The STEP file is the geometry delivery artifact — topology identity
    is carried alongside in the sidecar, not embedded in STEP (yet).

    Future (AP242 XCAF): embed face names directly in STEP using
    OCP STEPCAFControl_Writer + TDataStd_Name on XCAF faces.
    """

    @staticmethod
    def build_export_manifest(
        step_path: "str | Path",
        sidecar_path: "str | Path | None",
        registry: "TopologyRegistry | None" = None,
    ) -> dict:
        """Build an export manifest linking STEP, sidecar, and entity count.

        Args:
            step_path: Path to the exported STEP file.
            sidecar_path: Path to <part>.topology.json (if available).
            registry: TopologyRegistry for entity statistics.

        Returns:
            dict with export manifest suitable for import gate validation.
        """
        manifest: dict = {
            "step_path": str(step_path),
            "sidecar_path": str(sidecar_path) if sidecar_path else None,
            "topology_schema_version": "gcad_topology_v1",
            "has_topology_sidecar": sidecar_path is not None,
        }

        if registry is not None:
            manifest["entity_count"] = registry.entity_count
            manifest["active_count"] = registry.active_count
            manifest["deleted_count"] = registry.deleted_count

        return manifest

    @staticmethod
    def validate_export_consistency(
        step_path: "str | Path",
        sidecar_path: "str | Path | None",
        canonical_graph_hash: str,
    ) -> dict:
        """Check that STEP export is consistent with its topology sidecar.

        Returns {"ok": bool, "issues": list[dict]}.
        """
        issues: list[dict] = []

        if sidecar_path is None:
            issues.append({
                "code": "NO_TOPOLOGY_SIDECAR",
                "severity": "warning",
                "message": "STEP exported without topology sidecar. Face identity will not survive import.",
            })
            return {"ok": True, "issues": issues}  # Warning only

        import json
        from pathlib import Path

        sp = Path(sidecar_path)
        if not sp.exists():
            issues.append({
                "code": "SIDECAR_MISSING",
                "severity": "error",
                "message": f"Topology sidecar not found: {sidecar_path}",
            })
            return {"ok": False, "issues": issues}

        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
        except Exception as exc:
            issues.append({
                "code": "SIDECAR_INVALID_JSON",
                "severity": "error",
                "message": str(exc),
            })
            return {"ok": False, "issues": issues}

        # Check graph hash consistency
        sc_hash = data.get("canonical_graph_hash", "")
        if sc_hash and sc_hash != canonical_graph_hash:
            issues.append({
                "code": "GRAPH_HASH_MISMATCH",
                "severity": "error",
                "message": f"Sidecar hash {sc_hash} != canonical {canonical_graph_hash}",
            })

        # Check schema version
        schema = data.get("schema", "")
        if schema != "gcad_topology_v1":
            issues.append({
                "code": "SCHEMA_VERSION_MISMATCH",
                "severity": "warning",
                "message": f"Sidecar schema {schema} != gcad_topology_v1",
            })

        return {"ok": len([i for i in issues if i["severity"] == "error"]) == 0, "issues": issues}


# ═══════════════════════════════════════════════════════════════════════════════
# SolidWorksTopologyAdapter — SW attribute ↔ PersistentTopoId
# ═══════════════════════════════════════════════════════════════════════════════


class SolidWorksTopologyAdapter:
    """Map G-CAD PersistentTopoId to SolidWorks entity attributes.

    SolidWorks supports:
      - Body/Feature names (IPartDoc::get_Bodies, IBody2::Name)
      - Face colors (IMaterialPropertyValues)
      - Custom attributes via IAttributeDef / Parameter

    This adapter defines the contract. Actual COM calls are in
    solidworks/com_client.py.
    """

    # Reserved attribute name for storing PersistentTopoId
    TOPOLOGY_ATTRIBUTE_NAME = "GCAD_PersistentTopoId"

    @staticmethod
    def build_face_attribute_map(
        registry: "TopologyRegistry",
    ) -> dict[str, str]:
        """Build {face_name → persistent_id} map for SW attribute storage.

        Face names are derived from semantic roles for human readability
        in the SolidWorks feature tree.

        Args:
            registry: TopologyRegistry with entity records.

        Returns:
            Dict mapping SW-compatible face name → compact PersistentTopoId.
        """
        from seekflow_engineering_tools.generative_cad.topology.ids import PersistentTopoId

        attr_map: dict[str, str] = {}
        snapshot = registry.export_snapshot()
        for pid, data in snapshot.get("entities", {}).items():
            if data.get("status") != "active":
                continue
            try:
                topo_id = PersistentTopoId.from_compact(pid)
            except ValueError:
                continue

            # Build SW-compatible face name (max 255 chars, alphanumeric + _)
            sw_name = (
                f"GCAD_{topo_id.component_id}_{topo_id.producer_node_id}_"
                f"{topo_id.semantic_role.replace('/', '_')}"
            )[:255]
            attr_map[sw_name] = pid

        return attr_map

    @staticmethod
    def build_import_validation_spec(
        registry: "TopologyRegistry",
        expected_face_count: int = 0,
    ) -> dict:
        """Build validation spec for imported SW model against topology sidecar.

        Returns a dict that can be passed to a SW COM health check to
        verify that all expected faces are present in the imported model.
        """
        active_faces = 0
        face_roles: list[str] = []

        snapshot = registry.export_snapshot()
        for _pid, data in snapshot.get("entities", {}).items():
            if data.get("status") == "active" and data.get("entity_type") == "face":
                active_faces += 1
                role = data.get("semantic_role", "unknown")
                face_roles.append(role)

        return {
            "expected_active_faces": active_faces,
            "expected_face_roles": sorted(face_roles),
            "expected_body_count": 1,
            "tolerance_percentage": 5.0,  # Allow 5% face count variance
        }

    @staticmethod
    def build_import_proof(
        registry: "TopologyRegistry",
        sw_face_names: list[str],
    ) -> CrossBackendTopologyProof:
        """Match imported SW face names back to topology sidecar entities.

        Args:
            registry: TopologyRegistry from the G-CAD build.
            sw_face_names: List of face names found in the imported SW model.

        Returns:
            CrossBackendTopologyProof with entity mapping and match statistics.
        """
        mapping: dict[str, str] = {}
        unmatched: list[str] = []
        low_confidence: list[str] = []

        attr_map = SolidWorksTopologyAdapter.build_face_attribute_map(registry)
        snapshot = registry.export_snapshot()

        for sw_name in sw_face_names:
            if sw_name in attr_map:
                mapping[attr_map[sw_name]] = sw_name
            else:
                # Try partial match by semantic role
                matched = False
                for gcad_name, pid in attr_map.items():
                    # Extract semantic role parts for fuzzy matching
                    gcad_parts = set(gcad_name.lower().replace("gcad_", "").split("_"))
                    sw_parts = set(sw_name.lower().split("_"))
                    common = gcad_parts & sw_parts
                    if len(common) >= 2:
                        mapping[pid] = sw_name
                        low_confidence.append(pid)
                        matched = True
                        break
                if not matched:
                    unmatched.append(sw_name)

        total_active = sum(
            1 for _pid, d in snapshot.get("entities", {}).items()
            if d.get("status") == "active" and d.get("entity_type") == "face"
        )
        match_rate = len(mapping) / max(total_active, 1)

        return CrossBackendTopologyProof(
            source_backend="gcad_cadquery",
            target_backend="solidworks2025",
            entity_mapping=mapping,
            unmatched_ids=unmatched,
            low_confidence_ids=low_confidence,
            ok=match_rate >= 0.80,  # 80% match threshold
            match_rate=round(match_rate, 4),
            issues=(
                [{"code": "LOW_MATCH_RATE", "severity": "warning",
                  "message": f"Match rate {match_rate:.2%} < 80%"}] if match_rate < 0.80 else []
            ),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# NXTopologyAdapter — NX attribute ↔ PersistentTopoId
# ═══════════════════════════════════════════════════════════════════════════════


class NXTopologyAdapter:
    """Map G-CAD PersistentTopoId to NX user attributes.

    NX supports:
      - UF_ATTR_assign / UF_ATTR_read_value for user attributes on objects
      - NXObject.SetUserAttribute() in NXOpen Python
      - Journal-based attribute assignment

    This adapter defines the contract. Actual NXOpen calls are in
    nx/nx_bridge_bootstrap.py (runs inside NX session).
    """

    # Reserved attribute title for storing PersistentTopoId
    TOPOLOGY_ATTRIBUTE_TITLE = "GCAD_PERSISTENT_TOPO_ID"

    @staticmethod
    def build_journal_attribute_commands(
        registry: "TopologyRegistry",
    ) -> list[dict]:
        """Build NX journal commands to write topology attributes on faces.

        Each command is a dict that can be serialized to JSON and processed
        by the NX bridge journal (nx_bridge_bootstrap.py).

        Args:
            registry: TopologyRegistry with entity records.

        Returns:
            List of journal commands: [{"action": "set_face_attribute", ...}, ...]
        """
        commands: list[dict] = []
        snapshot = registry.export_snapshot()

        for pid, data in snapshot.get("entities", {}).items():
            if data.get("status") != "active":
                continue
            if data.get("entity_type") != "face":
                continue

            commands.append({
                "action": "set_face_attribute",
                "face_semantic_role": data.get("semantic_role", "unknown"),
                "producer_node_id": data.get("producer_node_id", ""),
                "attribute_title": NXTopologyAdapter.TOPOLOGY_ATTRIBUTE_TITLE,
                "attribute_value": pid,
            })

        return commands

    @staticmethod
    def build_journal_validation_commands(
        registry: "TopologyRegistry",
    ) -> list[dict]:
        """Build NX journal commands to validate topology attributes.

        After import, verify that each expected face has the correct
        topology attribute.
        """
        commands: list[dict] = []
        snapshot = registry.export_snapshot()

        for pid, data in snapshot.get("entities", {}).items():
            if data.get("status") != "active":
                continue
            if data.get("entity_type") != "face":
                continue

            commands.append({
                "action": "validate_face_attribute",
                "face_semantic_role": data.get("semantic_role", "unknown"),
                "attribute_title": NXTopologyAdapter.TOPOLOGY_ATTRIBUTE_TITLE,
                "expected_value": pid,
            })

        return commands

    @staticmethod
    def build_import_proof(
        registry: "TopologyRegistry",
        nx_validation_results: list[dict],
    ) -> CrossBackendTopologyProof:
        """Match NX validation results back to topology sidecar.

        Args:
            registry: TopologyRegistry from the G-CAD build.
            nx_validation_results: Results from NX validate_face_attribute commands.

        Returns:
            CrossBackendTopologyProof with entity mapping and match statistics.
        """
        mapping: dict[str, str] = {}
        unmatched: list[str] = []

        for result in nx_validation_results:
            pid = result.get("expected_value", "")
            if result.get("ok"):
                mapping[pid] = result.get("face_semantic_role", pid)
            else:
                unmatched.append(pid)

        snapshot = registry.export_snapshot()
        entities = snapshot.get("entities", {})
        total_active = sum(
            1 for _pid, d in entities.items()
            if d.get("status") == "active" and d.get("entity_type") == "face"
        )
        match_rate = len(mapping) / max(total_active, 1)

        return CrossBackendTopologyProof(
            source_backend="gcad_cadquery",
            target_backend="nx12",
            entity_mapping=mapping,
            unmatched_ids=unmatched,
            ok=match_rate >= 0.80,
            match_rate=round(match_rate, 4),
            issues=(
                [{"code": "LOW_MATCH_RATE", "severity": "warning",
                  "message": f"Match rate {match_rate:.2%} < 80%"}] if match_rate < 0.80 else []
            ),
        )
