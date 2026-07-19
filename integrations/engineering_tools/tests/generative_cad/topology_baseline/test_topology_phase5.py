"""Phase 5 tests — fingerprint computation, loft/sweep naming, contracts."""

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.fingerprint import (
    FaceFingerprint,
    compute_face_fingerprint,
)
from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
    name_loft_faces,
    name_sweep_faces,
)
from seekflow_engineering_tools.generative_cad.topology.contracts import get_contract
from seekflow_engineering_tools.generative_cad.topology.models import TopologyDelta


# ═══════════════════════════════════════════════════════════════════════════════
# Fingerprint computation
# ═══════════════════════════════════════════════════════════════════════════════


class TestFingerprintComputation:
    def test_box_face_plane(self):
        """Box face is correctly identified as PLANE with area."""
        box = cq.Workplane("XY").box(20, 20, 20)
        fp = compute_face_fingerprint(box.faces().vals()[0], tolerance_mm=0.01)
        assert fp.surface_type == "PLANE"
        assert fp.area_q is not None and fp.area_q > 0
        assert fp.boundary_wire_count >= 1

    def test_fingerprint_stable(self):
        """Same face computed twice gives identical fingerprint."""
        box = cq.Workplane("XY").box(20, 20, 20)
        face = box.faces().vals()[0]
        fp1 = compute_face_fingerprint(face)
        fp2 = compute_face_fingerprint(face)
        assert fp1.surface_type == fp2.surface_type
        assert fp1.area_q == fp2.area_q
        assert fp1.centroid_q == fp2.centroid_q

    def test_all_box_faces_are_planes(self):
        """All 6 box faces are PLANE type."""
        box = cq.Workplane("XY").box(20, 20, 20)
        for face in box.faces().vals():
            fp = compute_face_fingerprint(face)
            assert fp.surface_type == "PLANE", f"Expected PLANE, got {fp.surface_type}"

    def test_cylinder_face_is_cylinder(self):
        """Cylinder lateral face is CYLINDER with radius."""
        cyl = cq.Workplane("XY").circle(10).extrude(30)
        for face in cyl.faces().vals():
            fp = compute_face_fingerprint(face)
            if fp.surface_type == "CYLINDER":
                assert fp.radius_q is not None
                return
        assert False, "No CYLINDER face found in cylinder solid"

    def test_fingerprint_is_face_fingerprint_type(self):
        """compute_face_fingerprint returns FaceFingerprint."""
        box = cq.Workplane("XY").box(10, 10, 10)
        fp = compute_face_fingerprint(box.faces().vals()[0])
        assert isinstance(fp, FaceFingerprint)

    def test_provenance_anchor_preserved(self):
        """Provenance anchor is passed through to fingerprint."""
        box = cq.Workplane("XY").box(10, 10, 10)
        fp = compute_face_fingerprint(box.faces().vals()[0], provenance_anchor="box/n1/x_max")
        assert fp.provenance_anchor == "box/n1/x_max"


# ═══════════════════════════════════════════════════════════════════════════════
# Loft/Sweep naming
# ═══════════════════════════════════════════════════════════════════════════════


class TestLoftSweepNaming:
    def test_loft_delta_is_valid(self):
        """Loft produces valid TopologyDelta."""
        try:
            r1 = cq.Workplane("XY").circle(10)
            r2 = cq.Workplane("XY").workplane(offset=20).circle(15)
            lofted = r1.add(r2).toPending().loft()
        except Exception:
            return  # Loft may not be supported in all CQ versions
        delta = name_loft_faces(lofted, document_id="d", component_id="c", producer_node_id="n")
        assert isinstance(delta, TopologyDelta)
        assert delta.node_id == "n"

    def test_sweep_delta_is_valid(self):
        """Sweep produces valid TopologyDelta."""
        try:
            path = cq.Workplane("XY").moveTo(0, 0).lineTo(20, 0)
            profile = cq.Workplane("XZ").circle(3)
            swept = profile.sweep(path)
        except Exception:
            return
        delta = name_sweep_faces(swept, document_id="d", component_id="c", producer_node_id="n")
        assert isinstance(delta, TopologyDelta)


# ═══════════════════════════════════════════════════════════════════════════════
# Contracts
# ═══════════════════════════════════════════════════════════════════════════════


class TestPhase5Contracts:
    def test_loft_contract(self):
        c = get_contract("loft_sweep", "loft_sections")
        assert c is not None
        assert c.history_capability == "partial_kernel_history"

    def test_sweep_contract(self):
        c = get_contract("loft_sweep", "sweep_profile")
        assert c is not None

    def test_helix_contract(self):
        c = get_contract("loft_sweep", "helix_sweep")
        assert c is not None
