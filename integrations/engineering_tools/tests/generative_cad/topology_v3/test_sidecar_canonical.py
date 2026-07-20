"""PR-7: Sidecar V3 canonical serialization — §3 tests.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §3
"""

import math
import tempfile
from pathlib import Path

from seekflow_engineering_tools.generative_cad.topology.sidecar_canonical import (
    canonicalize_entities,
    canonicalize_float,
    canonicalize_sidecar,
    compute_integrity_hash,
)


class TestCanonicalizeFloat:
    """§3 — Float quantization."""

    def test_rounds_to_precision(self):
        assert canonicalize_float(3.1415926535, precision=4) == 3.1416

    def test_rejects_nan(self):
        try:
            canonicalize_float(float("nan"))
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "NaN" in str(e)

    def test_rejects_infinity(self):
        try:
            canonicalize_float(float("inf"))
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Infinity" in str(e)

    def test_accepts_zero(self):
        assert canonicalize_float(0.0) == 0.0

    def test_accepts_negative(self):
        assert canonicalize_float(-1.5, precision=1) == -1.5


class TestCanonicalizeEntities:
    """§3 — Deterministic entity ordering."""

    def test_sorts_by_persistent_id(self):
        entities = [
            {"persistent_id": "gct3_c", "entity_type": "face"},
            {"persistent_id": "gct3_a", "entity_type": "edge"},
            {"persistent_id": "gct3_b", "entity_type": "face"},
        ]
        result = canonicalize_entities(entities)
        assert [e["persistent_id"] for e in result] == ["gct3_a", "gct3_b", "gct3_c"]

    def test_handles_missing_persistent_id(self):
        entities = [
            {"entity_type": "face"},
            {"persistent_id": "gct3_a"},
            {"persistent_id": "", "entity_type": "edge"},
        ]
        result = canonicalize_entities(entities)
        assert len(result) == 3


class TestIntegrityHash:
    """§3 — Event hash chain."""

    def test_same_content_produces_same_hash(self):
        sidecar = {
            "document_lineage_id": "proj-001",
            "canonical_graph_hash": "abc123",
            "entities": [
                {"persistent_id": "gct3_a"},
                {"persistent_id": "gct3_b"},
            ],
            "lineage": [],
        }
        h1 = compute_integrity_hash(sidecar)
        h2 = compute_integrity_hash(sidecar)
        assert h1 == h2

    def test_different_entities_produces_different_hash(self):
        s1 = {"document_lineage_id": "a", "canonical_graph_hash": "h",
              "entities": [{"persistent_id": "gct3_x"}], "lineage": []}
        s2 = {"document_lineage_id": "a", "canonical_graph_hash": "h",
              "entities": [{"persistent_id": "gct3_y"}], "lineage": []}
        assert compute_integrity_hash(s1) != compute_integrity_hash(s2)

    def test_prev_hash_affects_result(self):
        sidecar = {"document_lineage_id": "a", "canonical_graph_hash": "h",
                   "entities": [], "lineage": []}
        h1 = compute_integrity_hash(sidecar, prev_hash="")
        h2 = compute_integrity_hash(sidecar, prev_hash="hash_from_prev_run")
        assert h1 != h2


class TestCanonicalizeSidecar:
    """§3 — Full canonicalization."""

    def test_entities_sorted_in_output(self):
        sidecar = {
            "document_lineage_id": "proj-001",
            "canonical_graph_hash": "abc123",
            "entities": [
                {"persistent_id": "gct3_z"},
                {"persistent_id": "gct3_a"},
            ],
            "lineage": [],
        }
        result = canonicalize_sidecar(sidecar)
        pids = [e["persistent_id"] for e in result["entities"]]
        assert pids == ["gct3_a", "gct3_z"]

    def test_integrity_hash_present_in_output(self):
        sidecar = {
            "document_lineage_id": "p1",
            "canonical_graph_hash": "h1",
            "entities": [{"persistent_id": "gct3_x"}],
            "lineage": [],
        }
        result = canonicalize_sidecar(sidecar)
        assert "integrity_hash" in result
        assert len(result["integrity_hash"]) == 64  # SHA-256 hex

    def test_canonicalizer_version_present(self):
        result = canonicalize_sidecar({
            "document_lineage_id": "p1", "canonical_graph_hash": "h1",
            "entities": [], "lineage": [],
        })
        assert result.get("canonicalizer_version") == "3.0.0"
