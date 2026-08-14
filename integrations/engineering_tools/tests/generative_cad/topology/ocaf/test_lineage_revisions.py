"""T12-b: multi-revision lineage orchestration + immutable snapshot publishing."""

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


FIXTURES = (
    Path(__file__).resolve().parents[3] / "fixtures" / "generative_cad"
)


def _make_revision(depth_mm: float):
    raw = json.loads((FIXTURES / "sketch_extrude_minimal.json").read_text(encoding="utf-8"))
    raw = copy.deepcopy(raw)
    raw["nodes"][0]["params"]["depth_mm"] = depth_mm
    canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
    assert canonical is not None and report.ok, f"canonicalization failed: {report.issues}"
    return canonical, bundle.to_metadata_dict()


class TestLineageRevisions:

    def test_three_revision_lineage_publishes_snapshots(self, tmp_path):
        pytest.importorskip("cadquery")

        rev1 = _make_revision(12)
        rev2 = _make_revision(20)
        rev3 = _make_revision(30)

        results = run_lineage_revisions(
            lineage_id="demo_lineage",
            output_root=tmp_path,
            revisions=[
                {"canonical": rev1[0], "validation_seed": rev1[1]},
                {"canonical": rev2[0], "validation_seed": rev2[1]},
                {"canonical": rev3[0], "validation_seed": rev3[1]},
            ],
        )

        assert all(r.ok for r in results), [r.error for r in results if not r.ok]
        assert len(results) == 3

        store = RevisionStore(tmp_path, "demo_lineage")
        assert store.head_revision_number == 3

        for n in (1, 2, 3):
            rev_dir = store.revision_dir(n)
            assert (rev_dir / "design.xbf").exists(), f"rev {n} missing XBF"
            assert (rev_dir / "model.step").exists(), f"rev {n} missing STEP"
            assert (rev_dir / "metadata.json").exists(), f"rev {n} missing metadata"

        # The final snapshot must reopen and carry a CurrentResult shape.
        final = OcafDocumentSession.open(store.revision_dir(3) / "design.xbf")
        comp = final.ensure_component("plate")
        feat = final.ensure_feature(comp, "n_base")
        current = final.get_current_result_shape(feat)
        assert current is not None, "final revision should have a CurrentResult"
        final.close()

    def test_selection_survives_across_revisions(self, tmp_path):
        pytest.importorskip("cadquery")
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

        rev1 = _make_revision(12)
        rev2 = _make_revision(20)
        rev3 = _make_revision(30)

        spec = SelectionSpec(
            selection_id="top_face",
            component_id="plate",
            face_selector=">Z",
            policy=SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )

        results = run_lineage_revisions(
            lineage_id="sel_lineage",
            output_root=tmp_path,
            revisions=[
                {"canonical": rev1[0], "validation_seed": rev1[1], "selection_specs": [spec]},
                {"canonical": rev2[0], "validation_seed": rev2[1]},
                {"canonical": rev3[0], "validation_seed": rev3[1]},
            ],
        )
        assert all(r.ok for r in results), [r.error for r in results if not r.ok]

        store = RevisionStore(tmp_path, "sel_lineage")
        final = OcafDocumentSession.open(store.revision_dir(3) / "design.xbf")
        svc = PersistentSelectionService(final)
        label_map = collect_tnaming_labels(final.design_root_label)
        resolution = svc.solve("top_face", label_map)
        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        final.close()

    def test_ir_selections_are_used(self, tmp_path):
        """Selections declared in the IR are read by the pipeline."""
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            SelectionResolutionStatus,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
            PersistentSelectionService,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
            collect_tnaming_labels,
        )

        raw = json.loads((FIXTURES / "sketch_extrude_minimal.json").read_text(encoding="utf-8"))
        raw["selections"] = [{
            "selection_id": "top_face",
            "component_id": "plate",
            "face_selector": ">Z",
            "entity_kind": "face",
            "cardinality": "exact_one",
        }]
        canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
        assert canonical is not None and report.ok
        assert len(canonical.selections) == 1

        results = run_lineage_revisions(
            lineage_id="ir_lineage",
            output_root=tmp_path,
            revisions=[{"canonical": canonical, "validation_seed": bundle.to_metadata_dict()}],
        )
        assert all(r.ok for r in results), [r.error for r in results if not r.ok]

        store = RevisionStore(tmp_path, "ir_lineage")
        final = OcafDocumentSession.open(store.revision_dir(1) / "design.xbf")
        svc = PersistentSelectionService(final)
        label_map = collect_tnaming_labels(final.design_root_label)
        resolution = svc.solve("top_face", label_map)
        assert resolution.status in (
            SelectionResolutionStatus.UNIQUE,
            SelectionResolutionStatus.AMBIGUOUS,
        )
        final.close()
