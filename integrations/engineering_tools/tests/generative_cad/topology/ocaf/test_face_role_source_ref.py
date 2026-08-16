"""FaceRoleSpec can use a semantic SourceEntityRef for stable keys."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    FaceRoleSpec,
    SourceEntityRef,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
    _stable_face_role_key,
)


def test_source_ref_key_takes_precedence():
    spec = FaceRoleSpec(
        role_key="face_3",
        shape=None,
        source_ref=SourceEntityRef(
            component_id="comp_a",
            feature_id="n_fillet",
            construction_role="adjacent_3",
            entity_kind=TopologyEntityKind.FACE,
        ),
    )
    key = _stable_face_role_key("face_3", spec)
    assert key == "fr:comp_a:n_fillet::adjacent_3:face"


def test_legacy_key_fallback():
    spec = FaceRoleSpec(role_key="face_3", shape=None)
    assert _stable_face_role_key("face_3", spec) == "face_3"
