"""PR-E: Selection v3 tests — entity dedup, area validation, Solve Worker (v5.0 §9)."""

import cadquery as cq
from OCP.TDF import TDF_LabelMap

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
    PersistentSelectionService, validate_semantics, explode_entities,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.solve_worker import (
    solve_in_subprocess,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation,
    EvolutionKind, TopologyEntityKind, ProofClass, SelectionPolicy,
    SelectionCardinality, SemanticContract, SelectionResolutionStatus,
)


# ===========================================================================
# T_E1: Entity dedup
# ===========================================================================

class TestEntityDedup:

    def test_explode_compound_dedups(self):
        """Compound with 6 faces → explode returns unique faces only."""
        box = cq.Workplane("XY").box(10, 20, 30).val()
        # Fuse box with itself → shape with same 6 faces
        fused = box.fuse(box)
        entities = explode_entities(fused.wrapped, TopologyEntityKind.FACE)
        # A box has 6 unique faces — even after self-fuse
        assert len(entities) == 6, f"Expected 6 unique faces, got {len(entities)}"


# ===========================================================================
# T_E2: Area range validation
# ===========================================================================

class TestAreaRangeValidation:

    def test_area_in_range_passes(self):
        """Face area within range → no errors."""
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = [f for f in box.Faces() if f.Center().z > 0][0]  # 10×20=200 area
        contract = SemanticContract(area_range=(190.0, 210.0))
        errors = validate_semantics([face.wrapped], contract)
        assert errors == [], f"Area in range should pass: {errors}"

    def test_area_out_of_range_fails(self):
        """Face area outside range → error reported."""
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = [f for f in box.Faces() if f.Center().z > 0][0]  # 200 area
        contract = SemanticContract(area_range=(10.0, 20.0))  # way too small
        errors = validate_semantics([face.wrapped], contract)
        assert len(errors) >= 1
        assert "area" in errors[0].lower()


# ===========================================================================
# T_E3: Normal extraction
# ===========================================================================

class TestNormalExtraction:

    def test_planar_face_normal_extracted(self):
        """Planar face normal is extracted correctly (≈+Z)."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import _get_normal

        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = [f for f in box.Faces() if f.Center().z > 0][0]
        normal = _get_normal(face.wrapped)
        assert normal is not None, "Should extract normal for planar face"
        # Normal should be close to (0, 0, 1) for >Z face
        assert abs(normal[2] - 1.0) < 0.01 or abs(normal[2] + 1.0) < 0.01, \
            f"Z component should be ±1, got {normal[2]}"


# ===========================================================================
# T_E4: Solve Worker (subprocess isolation)
# ===========================================================================

class TestSolveWorker:

    def test_solve_worker_normal(self, xbf_path_ascii):
        """Subprocess Solve returns valid result for normal document."""
        session = OcafDocumentSession.create()
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
        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(xbf_path_ascii)
        session.close()

        # Solve in subprocess
        result = solve_in_subprocess(xbf_path_ascii, "top", timeout=30)
        assert result.ok, f"Solve failed: {result.errors}"
        assert result.status in ("unique", "set", "ambiguous"), \
            f"Unexpected status: {result.status}"
        assert not result.native_crash

    def test_solve_worker_missing_file(self, ascii_tmpdir):
        """Missing XBF → Solve Worker returns error, no crash."""
        result = solve_in_subprocess(ascii_tmpdir / "nonexistent.xbf", "top")
        assert not result.ok
        assert len(result.errors) >= 1
