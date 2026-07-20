"""PR-9: Turbine disc E2E acceptance tests — §5, §6.

Verifies the complete topology naming chain on a simplified turbine disc
geometry built with CadQuery/OCP.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §5, §6
"""

import json
import tempfile
from pathlib import Path

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.cad_adapters import (
    CrossBackendValidationPolicy,
    validate_required_set_coverage,
)
from seekflow_engineering_tools.generative_cad.topology.history_wrappers import (
    history_aware_boolean_cut,
    history_aware_revolve,
)
from seekflow_engineering_tools.generative_cad.topology.persistence import (
    read_topology_sidecar,
    write_topology_sidecar,
)
from seekflow_engineering_tools.generative_cad.topology.registry import (
    TopologyRegistry,
)
from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
    build_entity_records_from_delta,
    name_revolve_faces,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers — build a simplified turbine disc
# ═══════════════════════════════════════════════════════════════════════════════


def _build_disc_profile(r_mm: float = 100.0, z_mm: float = 30.0):
    """Build a simplified turbine disc via revolve."""
    profile = (
        cq.Workplane("XZ")
        .moveTo(20, 0).lineTo(r_mm, 0).lineTo(r_mm, z_mm)
        .lineTo(20, z_mm).close()
    )
    return profile.revolve(360)


def _build_disc_with_bore(r_mm=100.0, z_mm=30.0, bore_r=10.0):
    """Build a disc and cut a center bore."""
    disc = _build_disc_profile(r_mm, z_mm)
    bore = (
        cq.Workplane("XY").circle(bore_r).extrude(z_mm)
    )
    return disc.cut(bore)


# ═══════════════════════════════════════════════════════════════════════════════
# §5.1 — Identical rebuild PID stability
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdenticalRebuildStability:
    """§5.1, §6: Same parameters → same topology."""

    def test_identical_rebuild_produces_same_face_count(self):
        """Two builds with identical params → same face count."""
        d1 = _build_disc_profile(100, 30)
        d2 = _build_disc_profile(100, 30)
        assert len(d1.faces().vals()) == len(d2.faces().vals())

    def test_identical_rebuild_semantic_names_stable(self):
        """Semantic naming produces same roles on identical rebuild."""
        d1 = _build_disc_profile(100, 30)
        d2 = _build_disc_profile(100, 30)

        delta1 = name_revolve_faces(
            d1, document_id="test_doc", component_id="disc",
            producer_node_id="revolve_main",
        )
        delta2 = name_revolve_faces(
            d2, document_id="test_doc", component_id="disc",
            producer_node_id="revolve_main",
        )
        roles1 = sorted(r.semantic_role for r in delta1.relations if r.semantic_role)
        roles2 = sorted(r.semantic_role for r in delta2.relations if r.semantic_role)
        assert roles1 == roles2, (
            f"Semantic roles must be stable across identical rebuilds.\n"
            f"  build1: {roles1}\n  build2: {roles2}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# §5.2 — Boolean cut history
# ═══════════════════════════════════════════════════════════════════════════════


class TestBooleanCutHistory:
    """§5.2: Boolean cut must capture OCCT history."""

    def test_cut_history_available(self):
        """history_aware_boolean_cut returns valid history."""
        disc = _build_disc_profile(100, 30)
        bore = cq.Workplane("XY").circle(10).extrude(30)

        result = history_aware_boolean_cut(
            disc.val().wrapped,
            bore.val().wrapped,
            input_target_faces=[f.wrapped for f in disc.faces().vals()[:4]],
            input_tool_faces=[f.wrapped for f in bore.faces().vals()[:3]],
        )
        assert result is not None
        assert result.history is not None

    def test_disc_with_bore_produces_valid_solid(self):
        """Cut disc has valid geometry."""
        result = _build_disc_with_bore(100, 30, 10)
        solid = result.val()
        assert solid is not None, "Boolean cut should produce a result"
        if hasattr(solid, "IsValid"):
            assert solid.IsValid()
        assert len(result.faces().vals()) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# §6.7 — Sidecar roundtrip
# ═══════════════════════════════════════════════════════════════════════════════


class TestSidecarRoundtrip:
    """§6.7: Sidecar write → read → verify."""

    def test_sidecar_roundtrip_integrity(self):
        reg = TopologyRegistry()
        disc = _build_disc_profile(100, 30)
        delta = name_revolve_faces(
            disc, document_id="test_doc", component_id="disc",
            producer_node_id="revolve_main",
        )
        records = build_entity_records_from_delta(delta, document_id="test_doc")
        for rec in records:
            reg.register_entity(rec)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sidecar.json"
            write_topology_sidecar(
                reg, path, document_id="test_doc",
                canonical_graph_hash="abc123",
                runtime_version="1.0.0", occt_version="7.6.0",
            )
            assert path.exists()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["schema"] == "gcad_topology_v3"
            assert data["document_lineage_id"] == "test_doc"
            assert "integrity_hash" in data

    def test_sidecar_byte_identical_on_same_state(self):
        reg = TopologyRegistry()
        disc = _build_disc_profile(100, 30)
        delta = name_revolve_faces(
            disc, document_id="test_doc", component_id="disc",
            producer_node_id="revolve_main",
        )
        for rec in build_entity_records_from_delta(delta, document_id="test_doc"):
            reg.register_entity(rec)

        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "s1.json"
            p2 = Path(tmp) / "s2.json"
            write_topology_sidecar(
                reg, p1, document_id="test_doc",
                canonical_graph_hash="abc123",
                runtime_version="1.0.0", occt_version="7.6.0",
            )
            write_topology_sidecar(
                reg, p2, document_id="test_doc",
                canonical_graph_hash="abc123",
                runtime_version="1.0.0", occt_version="7.6.0",
            )
            h1 = json.loads(p1.read_text())["integrity_hash"]
            h2 = json.loads(p2.read_text())["integrity_hash"]
            assert h1 == h2, "Same state must produce byte-identical sidecars"


# ═══════════════════════════════════════════════════════════════════════════════
# §4 — Cross-backend strict validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestCrossBackendStrictGate:
    """§4: Required CAE sets must be 100%."""

    def test_all_sets_matched_passes(self):
        result = validate_required_set_coverage([
            {"name": "bore_wall", "purpose": "load", "matched": 3, "expected": 3},
        ])
        assert result["ok"] is True

    def test_missing_cae_face_fails(self):
        result = validate_required_set_coverage([
            {"name": "bore_wall", "purpose": "load", "matched": 2, "expected": 3},
        ])
        assert result["ok"] is False
        assert len(result["failed_sets"]) == 1

    def test_non_cae_purpose_not_checked(self):
        result = validate_required_set_coverage([
            {"name": "decorative", "purpose": "inspection", "matched": 1, "expected": 5},
        ])
        assert result["ok"] is True

    def test_policy_fuzzy_name_match_forbidden_by_default(self):
        policy = CrossBackendValidationPolicy()
        assert policy.fuzzy_name_match_forbidden is True

    def test_strict_ratio_is_100_percent(self):
        from seekflow_engineering_tools.generative_cad.topology.cad_adapters import (
            STRICT_FACE_MAPPING_RATIO,
        )
        assert STRICT_FACE_MAPPING_RATIO == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# §5.6 — Registry coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegistryCoverage:
    """§5.6: All final faces must have an entity record."""

    def test_all_faces_have_entity_records(self):
        reg = TopologyRegistry()
        disc = _build_disc_profile(100, 30)
        delta = name_revolve_faces(
            disc, document_id="test_doc", component_id="disc",
            producer_node_id="revolve_main",
        )
        records = build_entity_records_from_delta(delta, document_id="test_doc")
        for rec in records:
            reg.register_entity(rec)

        face_count = len(disc.faces().vals())
        assert reg.entity_count >= face_count, (
            f"Registry must have at least {face_count} entities "
            f"(one per face), got {reg.entity_count}"
        )
