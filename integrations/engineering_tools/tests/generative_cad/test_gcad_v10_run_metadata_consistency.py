"""v1.0: run metadata consistency — deep copy, artifact validation match."""

import copy
from pathlib import Path


class TestRunMetadataConsistencyV10:
    def _canonical(self):
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalGcadDocument, CanonicalNode, CanonicalComponent,
        )
        return CanonicalGcadDocument(
            schema_version="g_cad_core_v0.2",
            canonical_version="canonical_gcad_v0.2",
            document_id="test", part_name="test", units="mm",
            trust_level="reference_geometry",
            raw_graph_hash="sha256:abc", canonical_graph_hash="sha256:def",
            selected_dialects=[],
            components=[CanonicalComponent(id="disk", owner_dialect="axisymmetric", root_node="n_body")],
            nodes=[CanonicalNode(
                id="n_body", component="disk", dialect="axisymmetric",
                op="revolve_profile", op_version="1.0.0", phase="base_solid",
                inputs=[], outputs=[{"name": "body", "type": "solid", "value_id": "v1"}],
                params={}, typed_params={},
            )],
            constraints={"require_step_file": True, "require_metadata_sidecar": True,
                         "require_closed_solid": True, "expected_body_count": 1,
                         "max_runtime_seconds": 120},
            safety={"non_flight_reference_only": True, "not_airworthy": True,
                    "not_certified": True, "not_for_manufacturing": True,
                    "not_for_installation": True, "no_structural_validation": True,
                    "no_life_prediction": True},
        )

    def test_run_does_not_mutate_validation_seed(self, tmp_path, monkeypatch):
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        seed = {
            "core_validation": {"ok": True, "stage": "cv", "issues": []},
            "dialect_semantics": {"ok": True, "stage": "ds", "issues": []},
            "geometry_preflight": {"ok": True, "stage": "gp", "issues": []},
            "inspection_validation": {"ok": False, "stage": "iv", "issues": []},
        }
        original = copy.deepcopy(seed)

        monkeypatch.setattr(
            "seekflow_engineering_tools.generative_cad.pipeline.run._run_components",
            lambda c, ctx: None,
        )
        monkeypatch.setattr(
            "seekflow_engineering_tools.generative_cad.pipeline.run._run_composition_or_select_final",
            lambda c, ctx: "solid:disk:n_body:body",
        )
        monkeypatch.setattr(
            "seekflow_engineering_tools.generative_cad.pipeline.run._export_final_solid",
            lambda hid, ctx: None,
        )

        run_canonical_gcad(
            self._canonical(),
            out_step=tmp_path / "part.step",
            metadata_path=tmp_path / "part.metadata.json",
            validation_seed=seed,
        )
        assert seed == original

    def test_run_passes_metadata_validation_to_artifact(self):
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline import run
        src = inspect.getsource(run.run_canonical_gcad)
        assert 'validation=metadata["validation"]' in src

    def test_run_has_artifact_consistency_guard(self):
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline import run
        src = inspect.getsource(run)
        assert "artifact/metadata validation mismatch" in src

    def test_run_imports_copy_deepcopy(self):
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline import run
        src = inspect.getsource(run)
        assert "import copy" in src or "from copy import" in src
        assert "deepcopy" in src
