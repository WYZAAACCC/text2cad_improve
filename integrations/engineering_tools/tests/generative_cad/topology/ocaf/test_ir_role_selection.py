"""IR-declared role_key selections flow through the pipeline."""

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
    SelectionResolutionStatus,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
    PersistentSelectionService,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
    collect_tnaming_labels,
)


FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "generative_cad"


class TestIrRoleSelection:
    def test_ir_role_key_selection(self, tmp_path):
        pytest.importorskip("cadquery")

        raw = json.loads((FIXTURES / "sketch_extrude_minimal.json").read_text(encoding="utf-8"))
        raw = copy.deepcopy(raw)
        raw["selections"] = [{
            "selection_id": "x_side",
            "component_id": "plate",
            "role_key": "+X",
            "entity_kind": "face",
            "cardinality": "exact_one",
        }]

        canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
        assert canonical is not None and report.ok, f"canonicalization failed: {report.issues}"
        assert len(canonical.selections) == 1
        assert canonical.selections[0].role_key == "+X"

        results = run_lineage_revisions(
            lineage_id="ir_role_lineage",
            output_root=tmp_path,
            revisions=[
                {"canonical": canonical, "validation_seed": bundle.to_metadata_dict()},
            ],
        )
        assert all(r.ok for r in results), [r.error for r in results if not r.ok]

        store = RevisionStore(tmp_path, "ir_role_lineage")
        final = OcafDocumentSession.open(store.revision_dir(1) / "design.xbf")
        svc = PersistentSelectionService(final)
        label_map = collect_tnaming_labels(final.design_root_label)
        resolution = svc.solve("x_side", label_map)

        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        final.close()
