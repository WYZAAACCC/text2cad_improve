"""Persistent face role: a named non-cap face survives across revisions.

Proves the role registry path end-to-end: Rev1 anchors a selection to the
"+X" side face of an extruded box (not a cap), and later revisions carry that
face identity forward via per-role Modify, so a fresh-process Solve returns
UNIQUE.
"""

import copy
import json
from pathlib import Path

import pytest

from seekflow_engineering_tools.generative_cad.pipeline.run import run_lineage_revisions
from seekflow_engineering_tools.generative_cad.validation.pipeline import (
    validate_and_canonicalize_with_bundle,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.revision_store import RevisionStore
from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionSpec,
    SelectionPolicy,
    TopologyEntityKind,
    SelectionResolutionStatus,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
    PersistentSelectionService,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
    collect_tnaming_labels,
)


FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "generative_cad"


def _make_revision(width_mm: float):
    raw = json.loads((FIXTURES / "sketch_extrude_minimal.json").read_text(encoding="utf-8"))
    raw = copy.deepcopy(raw)
    raw["nodes"][0]["params"]["width_mm"] = width_mm
    canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
    assert canonical is not None and report.ok, f"canonicalization failed: {report.issues}"
    return canonical, bundle.to_metadata_dict()


def _face_normal_and_centroid(face):
    """Return (normal, centroid_x) for a planar TopoDS_Face, or (None, None)."""
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    try:
        face_f = TopoDS.Face_s(face)
        adaptor = BRepAdaptor_Surface(face_f)
        if adaptor.GetType() != 0:
            return None, None
        d = adaptor.Plane().Position().Direction()
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face_f, props)
        c = props.CentreOfMass()
        return (
            (round(d.X(), 3), round(d.Y(), 3), round(d.Z(), 3)),
            round(c.X(), 3),
        )
    except Exception:
        return None, None


class TestFaceRoleLineage:
    def test_plus_x_side_face_survives_across_revisions(self, tmp_path):
        pytest.importorskip("cadquery")

        rev1 = _make_revision(120)
        rev2 = _make_revision(140)
        rev3 = _make_revision(160)

        spec = SelectionSpec(
            selection_id="x_side",
            component_id="plate",
            face_selector="",
            role_key="+X",
            policy=SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )

        results = run_lineage_revisions(
            lineage_id="role_lineage",
            output_root=tmp_path,
            revisions=[
                {"canonical": rev1[0], "validation_seed": rev1[1], "selection_specs": [spec]},
                {"canonical": rev2[0], "validation_seed": rev2[1]},
                {"canonical": rev3[0], "validation_seed": rev3[1]},
            ],
        )
        assert all(r.ok for r in results), [r.error for r in results if not r.ok]

        store = RevisionStore(tmp_path, "role_lineage")
        final = OcafDocumentSession.open(store.revision_dir(3) / "design.xbf")
        svc = PersistentSelectionService(final)
        label_map = collect_tnaming_labels(final.design_root_label)
        resolution = svc.solve("x_side", label_map)

        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        assert len(resolution.resolved_shapes) == 1

        normal, centroid_x = _face_normal_and_centroid(resolution.resolved_shapes[0])
        assert normal is not None
        assert abs(abs(normal[0]) - 1.0) < 0.01, f"expected +X-aligned normal, got {normal}"
        assert abs(normal[1]) < 0.01 and abs(normal[2]) < 0.01, f"expected X-normal, got {normal}"
        assert centroid_x > 0, f"expected the +X side face (centroid_x>0), got {centroid_x}"
        final.close()
