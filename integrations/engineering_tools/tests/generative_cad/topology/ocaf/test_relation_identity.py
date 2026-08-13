"""PR-D: Relation identity + Policy roundtrip + CAE entity kind tests (v5.0 §8-10)."""

import json

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import PersistentSelectionService
from seekflow_engineering_tools.generative_cad.topology.ocaf.cae_preflight import run_cae_preflight
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation,
    EvolutionKind, TopologyEntityKind, ProofClass, SelectionPolicy,
    SelectionCardinality, SemanticContract, CaeBinding, SelectionResolutionStatus,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import collect_tnaming_labels


# ===========================================================================
# T_R1: Policy roundtrip — write → save → open → read
# ===========================================================================

class TestPolicyRoundtrip:

    def test_policy_roundtrip(self, xbf_path_ascii):
        """Policy written in one session is recovered in another."""
        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = box.faces(">Z").val() if hasattr(box.faces(">Z"), 'val') else \
            [f for f in box.Faces() if f.Center().z > 0][0]

        # Prerequisite: write a builder first
        comp = session.ensure_component("comp_a")
        feat = session.ensure_feature(comp, "box_node")
        from OCP.TNaming import TNaming_Builder
        TNaming_Builder(feat.FindChild(2, True)).Generated(box.wrapped)

        service = PersistentSelectionService(session)
        policy = SelectionPolicy(
            entity_kind=TopologyEntityKind.FACE,
            cardinality=SelectionCardinality.EXACT_ONE,
            required_for_cae=True,
        )
        service.create("test_face", face.wrapped, box.wrapped, policy)

        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(xbf_path_ascii)
        session.close()

        # Reopen and read back
        reopened = OcafDocumentSession.open(xbf_path_ascii)
        # Access the _read_policy directly via a solve attempt
        sel_label = reopened.ensure_selection("test_face")
        service2 = PersistentSelectionService(reopened)
        recovered = service2._read_policy(sel_label)
        assert recovered is not None, "Policy should be recoverable from OCAF"
        assert recovered.entity_kind == TopologyEntityKind.FACE
        assert recovered.cardinality == SelectionCardinality.EXACT_ONE
        assert recovered.required_for_cae is True
        reopened.close()

    def test_contract_roundtrip(self, xbf_path_ascii):
        """SemanticContract written in one session is recovered in another."""
        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = [f for f in box.Faces() if f.Center().z > 0][0]

        from OCP.TNaming import TNaming_Builder
        comp = session.ensure_component("comp_a")
        feat = session.ensure_feature(comp, "box_node")
        TNaming_Builder(feat.FindChild(2, True)).Generated(box.wrapped)

        contract = SemanticContract(surface_type="Plane", zone_id="load_zone")
        service = PersistentSelectionService(session)
        service.create("cae_face", face.wrapped, box.wrapped, contract=contract)

        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(xbf_path_ascii)
        session.close()

        reopened = OcafDocumentSession.open(xbf_path_ascii)
        sel_label = reopened.ensure_selection("cae_face")
        service2 = PersistentSelectionService(reopened)
        recovered = service2._read_contract(sel_label)
        assert recovered is not None, "Contract should be recoverable from OCAF"
        assert recovered.surface_type == "Plane"
        assert recovered.zone_id == "load_zone"
        reopened.close()


# ===========================================================================
# T_R2: CAE entity kind check
# ===========================================================================

class TestCaeEntityKindCheck:

    def test_kind_mismatch_blocks_binding(self):
        """FACE binding rejects EDGE resolution."""
        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = [f for f in box.Faces() if f.Center().z > 0][0]

        from OCP.TNaming import TNaming_Builder
        comp = session.ensure_component("comp_a")
        feat = session.ensure_feature(comp, "box_node")
        TNaming_Builder(feat.FindChild(2, True)).Generated(box.wrapped)

        service = PersistentSelectionService(session)
        service.create("top", face.wrapped, box.wrapped,
                       SelectionPolicy(entity_kind=TopologyEntityKind.FACE))

        label_map = collect_tnaming_labels(session.design_root_label)
        resolution = service.solve("top", label_map)

        # Binding requires EDGE but selection resolves to FACE → must fail
        binding = CaeBinding(
            binding_id="test_binding",
            selection_id="top",
            analysis_role="load_face",
            required=True,
            allowed_entity_kinds=(TopologyEntityKind.EDGE,),  # mismatch!
        )
        result = run_cae_preflight([binding], service, label_map)
        assert not result.ok, "CAE preflight should fail when entity kind mismatches"
        session.close()

    def test_kind_match_passes(self):
        """FACE binding accepts FACE resolution."""
        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = [f for f in box.Faces() if f.Center().z > 0][0]

        from OCP.TNaming import TNaming_Builder
        comp = session.ensure_component("comp_a")
        feat = session.ensure_feature(comp, "box_node")
        TNaming_Builder(feat.FindChild(2, True)).Generated(box.wrapped)

        service = PersistentSelectionService(session)
        service.create("top2", face.wrapped, box.wrapped,
                       SelectionPolicy(entity_kind=TopologyEntityKind.FACE,
                                       cardinality=SelectionCardinality.SET_ALLOWED))

        label_map = collect_tnaming_labels(session.design_root_label)
        resolution = service.solve("top2", label_map)

        binding = CaeBinding(
            binding_id="test_binding2",
            selection_id="top2",
            analysis_role="load_face",
            required=True,
            allowed_entity_kinds=(TopologyEntityKind.FACE,),  # match!
            cardinality=SelectionCardinality.SET_ALLOWED,  # box has 6 faces
        )
        result = run_cae_preflight([binding], service, label_map)
        assert result.ok, f"CAE preflight should pass: {result.errors}"
        session.close()


# ===========================================================================
# T_R3: Relation Label via Index (not list position)
# ===========================================================================

class TestRelationLabelStability:

    def test_relation_tag_infrastructure_exists(self):
        """allocate_relation() produces a correct feature-scoped TagPath."""
        session = OcafDocumentSession.create()
        entry = session.label_index.allocate_relation(
            1000, 1001, "feature:test_node", "test_node/specific_face", 1,
        )
        assert entry is not None
        assert entry.key.object_kind == "relation"
        assert entry.key.object_id == "test_node/specific_face"
        # 100 -> Components(2) -> component_tag -> Features(2) -> feature_tag
        # -> EvolutionRelations(3) -> relation_tag
        assert entry.tag_path.tags == (100, 2, 1000, 2, 1001, 3, entry.tag_path.tags[-1])

    def test_writer_allocates_index_based_tags(self):
        """Writer allocates relation tags via the Index (no position fallback)."""
        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 10, 10).val()

        scope = TopologyCaptureScope(node_id="test_node", component_id="comp_a")
        rel = LiveEvolutionRelation(
            relation_id="test_node/face_0", operation_id="test_node",
            kind=EvolutionKind.PRIMITIVE, entity_kind=TopologyEntityKind.FACE,
            source_key="body", old_shape=None, new_shapes=(box.wrapped,),
            proof=ProofClass.EXACT_CONSTRUCTION,
        )
        batch = LiveEvolutionBatch(
            scope=scope, builder_kind="Test",
            result_shape=box.wrapped, context_shape=box.wrapped, relations=[rel],
        )
        written = TopologyNamingWriter(session).write_batch(batch)
        assert written >= 2  # 1 result shape + 1 face relation
        # The relation must now be recorded in the StableLabelIndex.
        entry = session.label_index.get_existing(
            "relation", "feature:test_node", "test_node/face_0",
        )
        assert entry is not None, "relation should be Index-allocated by the writer"

    def test_relation_tag_stable_and_distinct(self):
        """Same relation_id → same tag; different relation_id → different tag."""
        session = OcafDocumentSession.create()
        e1 = session.label_index.allocate_relation(1000, 1001, "feature:n", "rel_a", 1)
        e2 = session.label_index.allocate_relation(1000, 1001, "feature:n", "rel_b", 1)
        e3 = session.label_index.allocate_relation(1000, 1001, "feature:n", "rel_a", 1)
        assert e1.tag_path.tags[-1] != e2.tag_path.tags[-1]
        assert e1.tag_path.tags[-1] == e3.tag_path.tags[-1]

    def test_multiple_relations_no_collision(self):
        """5 relations written with Index-allocated tags don't collide."""
        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 10, 10).val()

        relations = []
        for i in range(5):
            relations.append(LiveEvolutionRelation(
                relation_id=f"test_node/face_{i}", operation_id="test_node",
                kind=EvolutionKind.PRIMITIVE, entity_kind=TopologyEntityKind.FACE,
                source_key=f"face_{i}", old_shape=None, new_shapes=(box.wrapped,),
                proof=ProofClass.EXACT_CONSTRUCTION,
            ))
        batch = LiveEvolutionBatch(
            scope=TopologyCaptureScope(node_id="test_node", component_id="comp_a"),
            builder_kind="Test", result_shape=box.wrapped,
            context_shape=box.wrapped, relations=relations,
        )
        written = TopologyNamingWriter(session).write_batch(batch)
        assert written >= 6  # 1 result shape + 5 face relations
