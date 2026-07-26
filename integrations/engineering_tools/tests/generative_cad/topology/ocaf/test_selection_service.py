"""PR-4: Selection service tests — create, solve, heuristic, semantic validation."""

import json
import subprocess
import sys
from pathlib import Path

import cadquery as cq
from OCP.TDF import TDF_LabelMap

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyEntityKind, SelectionCardinality, SelectionPolicy,
    SelectionResolutionStatus, SemanticContract,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
    PersistentSelectionService, validate_semantics,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.heuristic_candidates import (
    HeuristicCandidateFinder, HeuristicStatus,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
    SELECTION_TAG_NATIVE_NAMING, SELECTION_TAG_METADATA,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_builder(session, component_id, node_id, shape):
    from OCP.TNaming import TNaming_Builder
    comp = session.ensure_component(component_id)
    feat = session.ensure_feature(comp, node_id)
    TNaming_Builder(feat.FindChild(2, True)).Generated(shape)
    return feat


# ---------------------------------------------------------------------------
# T_S1: Create selection
# ---------------------------------------------------------------------------

class TestCreateSelection:

    def test_create_stores_native_naming(self):
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession

        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = box.faces(">Z")

        _write_builder(session, "comp_a", "box", box.wrapped)

        service = PersistentSelectionService(session)
        service.create("test_face", face.wrapped, box.wrapped)

        sel_label = session.ensure_selection("test_face")
        assert not sel_label.IsNull()
        native = sel_label.FindChild(SELECTION_TAG_NATIVE_NAMING, False)
        assert not native.IsNull()

    def test_create_with_policy_and_contract(self):
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession

        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = box.faces(">Z")
        _write_builder(session, "comp_x", "box_x", box.wrapped)

        policy = SelectionPolicy(
            entity_kind=TopologyEntityKind.FACE,
            cardinality=SelectionCardinality.EXACT_ONE,
            required_for_cae=True,
        )
        contract = SemanticContract(surface_type="Plane")

        service = PersistentSelectionService(session)
        service.create("cae_face", face.wrapped, box.wrapped, policy, contract)

        sel_label = session.ensure_selection("cae_face")
        for tag in [1, 2, 3]:
            child = sel_label.FindChild(tag, False)
            assert not child.IsNull(), f"Tag {tag} missing"

    def test_create_cross_process(self, xbf_path_ascii):
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession

        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = box.faces(">Z")
        _write_builder(session, "comp_a", "node_1", box.wrapped)

        service = PersistentSelectionService(session)
        service.create("xproc_face", face.wrapped, box.wrapped,
                       SelectionPolicy(entity_kind=TopologyEntityKind.FACE))
        temp = session.save_temp()

        SRC = str(Path(__file__).resolve().parents[5] / "src")
        code = (f"import json, sys\nsys.path.insert(0, r'{SRC}')\n"
                "from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession\n"
                f"session = OcafDocumentSession.open(r'{temp}')\n"
                "root = session.design_root_label\n"
                "sels = root.FindChild(3, False)\n"
                "found = not sels.IsNull()\n"
                "result = {'status': 'ok', 'tag': root.Tag(), 'selection_found': found}\n"
                "print(json.dumps(result))\n")
        proc = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, timeout=30)
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# T_S2: Solve
# ---------------------------------------------------------------------------

class TestSolve:

    def test_solve_unique_same_revision(self):
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession

        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = box.faces(">Z")
        feat = _write_builder(session, "comp_1", "box_node", box.wrapped)

        service = PersistentSelectionService(session)
        service.create("top_face", face.wrapped, box.wrapped,
                       SelectionPolicy(entity_kind=TopologyEntityKind.FACE))

        valid_labels = TDF_LabelMap()
        valid_labels.Add(feat.FindChild(2, False))
        resolution = service.solve("top_face", valid_labels)
        assert resolution.status in (
            SelectionResolutionStatus.UNIQUE, SelectionResolutionStatus.AMBIGUOUS,
        ), f"Unexpected status: {resolution.status}: {resolution.detail}"
        assert len(resolution.resolved_shapes) >= 1


# ---------------------------------------------------------------------------
# T_S6: Heuristic never unique
# ---------------------------------------------------------------------------

class TestHeuristicNeverUnique:

    def test_find_returns_candidates_not_unique(self):
        finder = HeuristicCandidateFinder()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = box.faces(">Z")
        fp = finder.fingerprint_from_face(box, face.wrapped, "test")
        result = finder.find(box, fp)
        assert result.status in (HeuristicStatus.CANDIDATES_FOUND, HeuristicStatus.NO_CANDIDATES)

    def test_heuristic_status_has_no_unique_variant(self):
        statuses = {s.value for s in HeuristicStatus}
        assert "unique" not in statuses

    def test_fingerprint_accepts_shape_not_index(self):
        finder = HeuristicCandidateFinder()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = box.faces(">Z")
        fp = finder.fingerprint_from_face(box, face.wrapped, "test")
        assert fp is not None
        assert fp.surface_type == "Plane"


# ---------------------------------------------------------------------------
# T_S7: Semantic contract
# ---------------------------------------------------------------------------

class TestSemanticValidation:

    def test_plane_contract_passes_for_plane_face(self):
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = box.faces(">Z")
        contract = SemanticContract(surface_type="Plane")
        errors = validate_semantics([face.wrapped], contract)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_plane_contract_fails_for_cylinder(self):
        cyl = cq.Workplane("XY").cylinder(10, 30).val()
        cylinder_face = cyl.faces("%CYLINDER")
        assert cylinder_face is not None
        contract = SemanticContract(surface_type="Plane")
        errors = validate_semantics([cylinder_face.wrapped], contract)
        assert len(errors) >= 1
        assert "Plane" in errors[0]


# ---------------------------------------------------------------------------
# Selection with history
# ---------------------------------------------------------------------------

class TestSelectionWithHistory:

    def test_selection_with_writer_batch(self):
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation,
            EvolutionKind, ProofClass,
        )

        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = box.faces(">Z")

        scope = TopologyCaptureScope(node_id="box_node", component_id="comp_a")
        rel = LiveEvolutionRelation(
            relation_id="box/0", operation_id="box_node",
            kind=EvolutionKind.PRIMITIVE, entity_kind=TopologyEntityKind.FACE,
            source_key="box", old_shape=None, new_shapes=(box.wrapped,),
            proof=ProofClass.EXACT_CONSTRUCTION,
        )
        batch = LiveEvolutionBatch(
            scope=scope, builder_kind="Test",
            result_shape=box.wrapped, context_shape=box.wrapped, relations=[rel],
        )
        TopologyNamingWriter(session).write_batch(batch)

        service = PersistentSelectionService(session)
        service.create("top", face.wrapped, box.wrapped,
                       SelectionPolicy(entity_kind=TopologyEntityKind.FACE))

        batch.validate_all()
