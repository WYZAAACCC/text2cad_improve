"""Stable relation identity via RelationKey."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    RelationKey,
    SourceEntityRef,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
    _stable_relation_id,
)


class TestRelationIdentityStableKey:
    def test_relation_key_takes_precedence(self):
        ref = SourceEntityRef(
            component_id="comp_a",
            feature_id="n_fillet",
            construction_role="face_3",
            entity_kind=TopologyEntityKind.FACE,
        )
        key = RelationKey(
            feature_id="n_fillet",
            source_entity_ref=ref,
            evolution_kind=EvolutionKind.MODIFIED,
            relation_role="adjacent",
        )
        rel = type(
            "Rel",
            (),
            {
                "relation_id": "legacy/face_3",
                "relation_key": key,
            },
        )()
        stable = _stable_relation_id(rel)
        assert stable.startswith("rk:n_fillet:comp_a:n_fillet")
        assert "face_3" in stable

    def test_legacy_relation_id_fallback(self):
        rel = type(
            "Rel",
            (),
            {
                "relation_id": "legacy/face_3",
                "relation_key": None,
            },
        )()
        assert _stable_relation_id(rel) == "legacy/face_3"
