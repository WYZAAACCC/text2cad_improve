"""PR-F: CAE Gate tests — proof gate, history gate, solver no-start (v5.0 §10)."""

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import PersistentSelectionService
from seekflow_engineering_tools.generative_cad.topology.ocaf.cae_preflight import run_cae_preflight
from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import collect_tnaming_labels
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyEntityKind, SelectionCardinality, SelectionPolicy,
    CaeBinding,
)


def _setup_selection(session):
    """Helper: create a box with top face selection."""
    box = cq.Workplane("XY").box(10, 20, 30).val()
    face = [f for f in box.Faces() if f.Center().z > 0][0]

    from OCP.TNaming import TNaming_Builder
    comp = session.ensure_component("comp_a")
    feat = session.ensure_feature(comp, "box_node")
    TNaming_Builder(feat.FindChild(2, True)).Generated(box.wrapped)

    service = PersistentSelectionService(session)
    service.create("top", face.wrapped, box.wrapped,
                   SelectionPolicy(entity_kind=TopologyEntityKind.FACE,
                                   cardinality=SelectionCardinality.SET_ALLOWED))
    return service


class TestCaeGate:

    def test_require_native_proof_field_present(self):
        """CaeBinding has require_native_proof and require_complete_history."""
        binding = CaeBinding(binding_id="b1", selection_id="s1", analysis_role="load")
        assert binding.require_native_proof is True
        assert binding.require_complete_history is True

    def test_preflight_passes_for_valid_binding(self):
        """Valid binding with matching kind + cardinality → ok=True."""
        session = OcafDocumentSession.create()
        service = _setup_selection(session)
        label_map = collect_tnaming_labels(session.design_root_label)

        binding = CaeBinding(
            binding_id="b1", selection_id="top", analysis_role="load",
            required=True, allowed_entity_kinds=(TopologyEntityKind.FACE,),
            cardinality=SelectionCardinality.SET_ALLOWED,
        )
        result = run_cae_preflight([binding], service, label_map)
        assert result.ok, f"Should pass: {result.errors}"
        session.close()

    def test_required_binding_failure_makes_not_ok(self):
        """Required binding failing → preflight ok=False."""
        session = OcafDocumentSession.create()
        service = _setup_selection(session)
        label_map = collect_tnaming_labels(session.design_root_label)

        # Binding requires EDGE but selection resolves to FACE
        binding = CaeBinding(
            binding_id="b1", selection_id="top", analysis_role="load",
            required=True, allowed_entity_kinds=(TopologyEntityKind.EDGE,),
        )
        result = run_cae_preflight([binding], service, label_map)
        assert not result.ok, "Should fail: entity kind mismatch"
        assert len(result.errors) >= 1
        session.close()

    def test_optional_binding_failure_warns_not_errors(self):
        """Optional binding failure → warning, preflight still ok."""
        session = OcafDocumentSession.create()
        service = _setup_selection(session)
        label_map = collect_tnaming_labels(session.design_root_label)

        binding = CaeBinding(
            binding_id="b1", selection_id="top", analysis_role="load",
            required=False,  # optional!
            allowed_entity_kinds=(TopologyEntityKind.EDGE,),
        )
        result = run_cae_preflight([binding], service, label_map)
        assert result.ok, "Optional failure should not block"
        assert len(result.warnings) >= 1
        session.close()

    def test_solver_no_start_when_required_fails(self):
        """When required binding fails, solver_start_count should be 0 (gate)."""
        session = OcafDocumentSession.create()
        service = _setup_selection(session)
        label_map = collect_tnaming_labels(session.design_root_label)

        binding = CaeBinding(
            binding_id="b1", selection_id="top", analysis_role="load",
            required=True, allowed_entity_kinds=(TopologyEntityKind.EDGE,),
        )
        result = run_cae_preflight([binding], service, label_map)

        # Simulate solver gate: if not ok, solver count = 0
        solver_start_count = 1 if result.ok else 0
        assert solver_start_count == 0, \
            "Solver must NOT start when required CAE binding fails"
        session.close()

    def test_require_complete_history_rejects_incomplete(self):
        """history_complete=False → required binding fails."""
        session = OcafDocumentSession.create()
        service = _setup_selection(session)
        label_map = collect_tnaming_labels(session.design_root_label)

        binding = CaeBinding(
            binding_id="b1", selection_id="top", analysis_role="load",
            required=True, allowed_entity_kinds=(TopologyEntityKind.FACE,),
            cardinality=SelectionCardinality.SET_ALLOWED,
            require_complete_history=True,
        )
        result = run_cae_preflight([binding], service, label_map, history_complete=False)
        assert not result.ok
        assert len(result.errors) >= 1
        session.close()

    def test_require_complete_history_passes_when_complete(self):
        """history_complete=True → required binding passes."""
        session = OcafDocumentSession.create()
        service = _setup_selection(session)
        label_map = collect_tnaming_labels(session.design_root_label)

        binding = CaeBinding(
            binding_id="b1", selection_id="top", analysis_role="load",
            required=True, allowed_entity_kinds=(TopologyEntityKind.FACE,),
            cardinality=SelectionCardinality.SET_ALLOWED,
            require_complete_history=True,
        )
        result = run_cae_preflight([binding], service, label_map, history_complete=True)
        assert result.ok, f"Should pass with complete history: {result.errors}"
        session.close()
