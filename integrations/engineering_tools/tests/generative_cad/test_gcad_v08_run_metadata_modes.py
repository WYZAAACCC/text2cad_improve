"""v0.8: run metadata modes — require_full_validation_seed, raw path full proof."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures" / "generative_cad"


class TestRunMetadataModes:
    def test_run_canonical_requires_seed_when_requested(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalGcadDocument, CanonicalNode, CanonicalComponent,
        )

        canonical = CanonicalGcadDocument(
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

        result = run_canonical_gcad(
            canonical,
            out_step=tmp_path / "part.step",
            metadata_path=tmp_path / "part.metadata.json",
            validation_seed=None,
            require_full_validation_seed=True,
        )
        assert not result.ok
        assert ("requires validation_seed" in result.error) or ("requires non-empty validation_seed" in result.error)

    def test_run_canonical_accepts_seed_without_requirement(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalGcadDocument, CanonicalNode, CanonicalComponent,
        )

        canonical = CanonicalGcadDocument(
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

        # Without require_full_validation_seed, None seed should not fail upfront
        result = run_canonical_gcad(
            canonical,
            out_step=tmp_path / "part.step",
            metadata_path=tmp_path / "part.metadata.json",
            validation_seed=None,
            require_full_validation_seed=False,
        )
        # May fail at runtime (no actual cadquery available), but should not fail at seed check
        if not result.ok:
            assert "requires validation_seed" not in (result.error or "")

    def test_run_gcad_core_passes_require_full_validation_seed(self):
        """Verify run_gcad_core passes require_full_validation_seed=True."""
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_gcad_core
        src = inspect.getsource(run_gcad_core)
        assert "require_full_validation_seed=True" in src

    def test_run_canonical_gcad_accepts_require_full_validation_seed_param(self):
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        sig = inspect.signature(run_canonical_gcad)
        assert "require_full_validation_seed" in sig.parameters
