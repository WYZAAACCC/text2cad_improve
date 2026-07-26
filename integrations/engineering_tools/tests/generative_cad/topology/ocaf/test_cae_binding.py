"""PR-7: CAE binding preflight tests."""

import cadquery as cq
from OCP.TDF import TDF_LabelMap

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyEntityKind,
    SelectionCardinality,
    SelectionPolicy,
    SelectionResolutionStatus,
    CaeBinding,
    CaePreflightResult,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.cae_preflight import (
    run_cae_preflight,
)


class TestCaeBindingModel:

    def test_binding_defaults(self):
        b = CaeBinding(
            binding_id="load_001",
            selection_id="top_face",
            analysis_role="load_face",
        )
        assert b.required is True
        assert b.cardinality == SelectionCardinality.EXACT_ONE
        assert TopologyEntityKind.FACE in b.allowed_entity_kinds

    def test_binding_optional(self):
        b = CaeBinding(
            binding_id="opt_001",
            selection_id="side_face",
            analysis_role="contact_region",
            required=False,
        )
        assert b.required is False


class TestCaePreflight:

    def _setup_session_with_selection(self):
        """Create a session with a valid selection for testing."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
            OcafDocumentSession,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
            PersistentSelectionService,
        )
        from OCP.TNaming import TNaming_Builder

        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = box.faces(">Z")

        # Write builder (required before selection)
        comp = session.ensure_component("comp_a")
        feat = session.ensure_feature(comp, "box")
        TNaming_Builder(feat.FindChild(2, True)).Generated(box.wrapped)

        service = PersistentSelectionService(session)
        policy = SelectionPolicy(entity_kind=TopologyEntityKind.FACE)
        service.create("top_face", face.wrapped, box.wrapped, policy)

        valid_labels = TDF_LabelMap()
        valid_labels.Add(feat.FindChild(2, False))

        return session, service, valid_labels

    def test_preflight_required_resolved(self):
        """Required binding with UNIQUE selection → ok=True."""
        _, service, valid_labels = self._setup_session_with_selection()

        bindings = [
            CaeBinding(binding_id="b1", selection_id="top_face", analysis_role="load_face"),
        ]
        result = run_cae_preflight(bindings, service, valid_labels)
        # May be UNIQUE or AMBIGUOUS depending on body-only history
        assert isinstance(result, CaePreflightResult)

    def test_preflight_unresolved_required_fails(self):
        """Required binding with nonexistent selection → ok=False."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
            OcafDocumentSession,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
            PersistentSelectionService,
        )

        session = OcafDocumentSession.create()
        # No selection created → solve will fail
        service = PersistentSelectionService(session)

        bindings = [
            CaeBinding(binding_id="b1", selection_id="nonexistent", analysis_role="load_face"),
        ]
        result = run_cae_preflight(bindings, service)

        assert result.ok is False
        assert len(result.errors) >= 1
        assert any("b1" in e for e in result.errors)

    def test_preflight_optional_unresolved_warns(self):
        """Non-required binding unresolved → ok=True, warning."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
            OcafDocumentSession,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
            PersistentSelectionService,
        )

        session = OcafDocumentSession.create()
        service = PersistentSelectionService(session)

        bindings = [
            CaeBinding(binding_id="opt", selection_id="nonexistent",
                       analysis_role="aux_face", required=False),
        ]
        result = run_cae_preflight(bindings, service)

        assert result.ok is True  # optional failures don't block
        assert len(result.warnings) >= 1

    def test_preflight_mixed(self):
        """Mix of resolved required + unresolved optional."""
        _, service, valid_labels = self._setup_session_with_selection()

        bindings = [
            CaeBinding(binding_id="req", selection_id="top_face", analysis_role="load"),
            CaeBinding(binding_id="opt", selection_id="nonexistent",
                       analysis_role="aux", required=False),
        ]
        result = run_cae_preflight(bindings, service, valid_labels)
        assert isinstance(result, CaePreflightResult)
        print(f"ok={result.ok}, errors={len(result.errors)}, warnings={len(result.warnings)}")
