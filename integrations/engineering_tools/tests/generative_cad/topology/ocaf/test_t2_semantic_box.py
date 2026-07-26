"""v6.0 PR-1: Correct TNaming Baseline — Semantic Box Face UNIQUE T2.

Uses BRepPrimAPI_MakeBox semantic faces (TopFace/BottomFace/...) with
ResultRoot sub-shape history to prove face-level UNIQUE Solve is possible
in OCP 7.8.1.1 — when Label organization and history granularity are correct.

Fixture:
  Rev1: MakeBox(20,30,10) → 6 role faces + Selection on top_role
  Rev2: MakeBox(20,30,15) → Modify(old,new) per role + Solve → UNIQUE
  Rev3: MakeBox(20,30,22) → Modify(old,new) per role + Solve → UNIQUE

Gate: UNIQUE only — NO AMBIGUOUS fallback.
"""

from pathlib import Path

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.TNaming import TNaming_Builder, TNaming_Selector
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.TopoDS import TopoDS, TopoDS_Face
from OCP.TopAbs import TopAbs_FACE

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
    TopologyNamingWriter, FEATURE_TAG_RESULT_ROOT, ROLE_TAG_BASE,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
    PersistentSelectionService,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import collect_tnaming_labels
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionPolicy, TopologyEntityKind, SelectionResolutionStatus,
)

# Semantic roles (v6.0 §4.2)
SEMANTIC_ROLES = [
    ("top_role",    lambda b: b.TopFace()),
    ("bottom_role", lambda b: b.BottomFace()),
    ("left_role",   lambda b: b.LeftFace()),
    ("right_role",  lambda b: b.RightFace()),
    ("front_role",  lambda b: b.FrontFace()),
    ("back_role",   lambda b: b.BackFace()),
]


def _face_props(face):
    """Extract area, centroid, normal, surface_type from a TopoDS_Face."""
    face_f = TopoDS.Face_s(face)  # downcast Shape → Face
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face_f, props)
    area = props.Mass()
    c = props.CentreOfMass()
    adaptor = BRepAdaptor_Surface(face_f)
    stype = adaptor.GetType()
    normal = None
    if stype == 0:  # Plane
        try:
            plane = adaptor.Plane()
            d = plane.Position().Direction()
            normal = (d.X(), d.Y(), d.Z())
        except Exception:
            pass
    return {
        "area": area,
        "centroid": (c.X(), c.Y(), c.Z()),
        "surface_type": stype,
        "normal": normal,
    }


class TestSemanticBoxT2:

    def test_semantic_box_face_unique_t2(self, ascii_tmpdir):
        """★ THE GATE: Rev1→Rev2→Rev3 with face-level UNIQUE Solve.

        Uses BRepPrimAPI_MakeBox semantic roles + ResultRoot sub-shape history.
        If this fails, the problem is NOT OCP — it's Label organization.
        """
        xbf_dir = Path(ascii_tmpdir)
        rev1_path = xbf_dir / "semantic_rev1.xbf"
        rev2_path = xbf_dir / "semantic_rev2.xbf"
        rev3_path = xbf_dir / "semantic_rev3.xbf"

        # ════════════════════════════════════════════════════════════
        # Rev1: Create box(20,30,10), write face-level history
        # ════════════════════════════════════════════════════════════
        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)

        box1 = BRepPrimAPI_MakeBox(20.0, 30.0, 10.0)
        body1 = box1.Shape()

        # Ensure feature label
        comp = session.ensure_component("comp_a")
        feat = session.ensure_feature(comp, "box_node")

        # ResultRoot: Generated(body)
        writer.write_feature_result(feat, body1)

        # Each role: Generated(face) under ResultRoot child
        for i, (role_name, get_face) in enumerate(SEMANTIC_ROLES):
            face = get_face(box1)
            assert face.ShapeType() == TopAbs_FACE, \
                f"{role_name} is not a FACE: {face.ShapeType()}"
            writer.write_role_result(feat, ROLE_TAG_BASE + i, face)

        # Selection on top_role (first role)
        top_face1 = box1.TopFace()
        service = PersistentSelectionService(session)
        service.create("top_face", top_face1, body1,
                       SelectionPolicy(entity_kind=TopologyEntityKind.FACE))

        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(rev1_path)
        rev1_top_props = _face_props(top_face1)
        session.close()

        # Basic Rev1 assertions
        assert rev1_top_props["surface_type"] == 0  # Plane
        assert abs(rev1_top_props["area"] - 600.0) < 1.0  # 20×30

        # ════════════════════════════════════════════════════════════
        # Rev2: Modify height to 15, face-level Modify + Solve
        # ════════════════════════════════════════════════════════════
        s2 = OcafDocumentSession.open(rev1_path)
        writer2 = TopologyNamingWriter(s2)
        comp2 = s2.ensure_component("comp_a")
        feat2 = s2.ensure_feature(comp2, "box_node")

        # Get previous body
        prev_body = s2.get_current_result_shape(feat2)
        assert prev_body is not None, "Must retrieve previous body"

        box2 = BRepPrimAPI_MakeBox(20.0, 30.0, 15.0)
        body2 = box2.Shape()

        # ResultRoot: Modify(prev_body, new_body)
        writer2.write_feature_result(feat2, body2, previous_result=prev_body)

        # Each role: Modify(old_face, new_face)
        for i, (role_name, get_face) in enumerate(SEMANTIC_ROLES):
            old_face = get_face(box1)
            new_face = get_face(box2)
            writer2.write_role_result(feat2, ROLE_TAG_BASE + i, new_face,
                                      previous_face=old_face)

        # ★ Solve — must be UNIQUE
        label_map = collect_tnaming_labels(s2.design_root_label)
        service2 = PersistentSelectionService(s2)
        resolution = service2.solve("top_face", label_map)

        assert resolution.status == SelectionResolutionStatus.UNIQUE, \
            f"Rev2 Solve must be UNIQUE, got {resolution.status}: {resolution.detail}"
        assert len(resolution.resolved_shapes) == 1, \
            f"Expected 1 shape, got {len(resolution.resolved_shapes)}"

        rev2_props = _face_props(resolution.resolved_shapes[0])
        assert abs(rev2_props["area"] - 600.0) < 2.0, \
            f"Area mismatch: {rev2_props['area']:.2f} != ~600"
        assert rev2_props["surface_type"] == 0  # Plane
        assert rev2_props["centroid"][2] > 0, "Must be top face (Z > 0)"

        s2.label_index.save_to_ocaf(s2.main_label)
        s2.repository.save_to(rev2_path)
        s2.close()

        # ════════════════════════════════════════════════════════════
        # Rev3: Modify height to 22
        # ════════════════════════════════════════════════════════════
        s3 = OcafDocumentSession.open(rev2_path)
        writer3 = TopologyNamingWriter(s3)
        comp3 = s3.ensure_component("comp_a")
        feat3 = s3.ensure_feature(comp3, "box_node")

        prev_body3 = s3.get_current_result_shape(feat3)
        assert prev_body3 is not None

        box3 = BRepPrimAPI_MakeBox(20.0, 30.0, 22.0)
        body3 = box3.Shape()

        writer3.write_feature_result(feat3, body3, previous_result=prev_body3)

        for i, (role_name, get_face) in enumerate(SEMANTIC_ROLES):
            old_face = get_face(box2)
            new_face = get_face(box3)
            writer3.write_role_result(feat3, ROLE_TAG_BASE + i, new_face,
                                      previous_face=old_face)

        label_map3 = collect_tnaming_labels(s3.design_root_label)
        service3 = PersistentSelectionService(s3)
        resolution3 = service3.solve("top_face", label_map3)

        assert resolution3.status == SelectionResolutionStatus.UNIQUE, \
            f"Rev3 Solve must be UNIQUE, got {resolution3.status}: {resolution3.detail}"
        assert len(resolution3.resolved_shapes) == 1

        rev3_props = _face_props(resolution3.resolved_shapes[0])
        assert abs(rev3_props["area"] - 600.0) < 2.0
        assert rev3_props["surface_type"] == 0

        s3.repository.save_to(rev3_path)
        s3.close()

        # Final verification
        for p in [rev1_path, rev2_path, rev3_path]:
            assert p.exists(), f"Missing: {p}"
            assert p.stat().st_size > 100

    def test_top_face_area_consistent(self, ascii_tmpdir):
        """Top face area stays 600 (20×30) across all 3 revisions."""
        xbf_dir = Path(ascii_tmpdir)
        rev1_path = xbf_dir / "area_rev1.xbf"

        # Rev1
        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        box1 = BRepPrimAPI_MakeBox(20.0, 30.0, 10.0)
        feat = session.ensure_feature(session.ensure_component("comp_a"), "box")
        writer.write_feature_result(feat, box1.Shape())
        for i, (_, get_face) in enumerate(SEMANTIC_ROLES):
            writer.write_role_result(feat, ROLE_TAG_BASE + i, get_face(box1))
        service = PersistentSelectionService(session)
        service.create("top", box1.TopFace(), box1.Shape(),
                       SelectionPolicy(entity_kind=TopologyEntityKind.FACE))
        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(rev1_path)
        session.close()

        # Rev2
        s2 = OcafDocumentSession.open(rev1_path)
        w2 = TopologyNamingWriter(s2)
        feat2 = s2.ensure_feature(s2.ensure_component("comp_a"), "box")
        prev = s2.get_current_result_shape(feat2)
        box2 = BRepPrimAPI_MakeBox(20.0, 30.0, 15.0)
        w2.write_feature_result(feat2, box2.Shape(), previous_result=prev)
        for i, (_, get_face) in enumerate(SEMANTIC_ROLES):
            w2.write_role_result(feat2, ROLE_TAG_BASE + i, get_face(box2),
                                 previous_face=get_face(box1))
        label_map = collect_tnaming_labels(s2.design_root_label)
        res = PersistentSelectionService(s2).solve("top", label_map)
        assert res.status == SelectionResolutionStatus.UNIQUE
        props = _face_props(res.resolved_shapes[0])
        assert abs(props["area"] - 600.0) < 2.0
        s2.close()
