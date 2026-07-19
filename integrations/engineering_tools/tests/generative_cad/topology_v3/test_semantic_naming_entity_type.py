"""Phase 5 tests — semantic naming evidence contains entity_type."""

from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
    _infer_entity_type,
)


class TestEntityTypeInference:
    """V3: _infer_entity_type uses evidence.entity_type, not role guessing."""

    def test_entity_type_from_evidence(self):
        """Direct evidence lookup — no guessing."""
        result = _infer_entity_type(
            semantic_role="some/random/role",
            evidence={"entity_type": "edge", "method": "test"},
        )
        assert result == "edge"

    def test_entity_type_fallback_face(self):
        """No evidence → default 'face'."""
        result = _infer_entity_type(
            semantic_role=None,
            evidence={},
        )
        assert result == "face"

    def test_role_prefix_fallback_still_works(self):
        """Legacy: role prefix 'edge/xxx' still works when no evidence."""
        result = _infer_entity_type(
            semantic_role="edge/hole/entry_rim",
            evidence={"method": "old_style_no_entity_type"},
        )
        assert result == "edge"

    def test_no_more_heuristic_guessing(self):
        """No evidence + no prefix → 'face', not guessing from 'rim'/'wall'."""
        result = _infer_entity_type(
            semantic_role="hole/entry_rim",
            evidence={"method": "some_method"},
        )
        # Previously: "rim" → edge heuristic. Now: falls through to default
        assert result == "face"

    def test_entity_type_face_from_evidence(self):
        result = _infer_entity_type(
            semantic_role="box/x_max",
            evidence={"entity_type": "face", "method": "bbox_extreme_normal"},
        )
        assert result == "face"
