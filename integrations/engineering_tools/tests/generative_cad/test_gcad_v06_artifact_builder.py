"""v0.6: artifact builder signature and semantic tests."""

from pathlib import Path
import json

FIXTURES = Path(__file__).parent.parent / "fixtures" / "generative_cad"


class TestArtifactBuilder:
    def test_artifact_builder_accepts_builder_signature(self):
        from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
        from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument

        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        canonical = CanonicalGcadDocument.model_validate({
            "schema_version": "g_cad_core_v0.2",
            "canonical_version": "canonical_gcad_v0.2",
            "document_id": "test",
            "part_name": "test",
            "units": "mm",
            "trust_level": "reference_geometry",
            "raw_graph_hash": "sha256:abc",
            "canonical_graph_hash": "sha256:def",
            "selected_dialects": [],
            "components": [],
            "nodes": [],
            "constraints": {"require_step_file": True, "require_metadata_sidecar": True, "require_closed_solid": True, "expected_body_count": 1, "max_runtime_seconds": 120},
            "safety": {"non_flight_reference_only": True, "not_airworthy": True, "not_certified": True, "not_for_manufacturing": True, "not_for_installation": True, "no_structural_validation": True, "no_life_prediction": True},
        })

        artifact = build_canonical_step_artifact(
            canonical=canonical,
            step_path=Path("/tmp/a.step"),
            metadata_path=Path("/tmp/a.metadata.json"),
            graph_path="/tmp/graph.json",
            runner_script_path="/tmp/run.py",
            validation={"core_validation": {"ok": True}},
        )
        assert "graph.json" in artifact["graph_path"]
        assert "run.py" in artifact["runner_script_path"]
        assert artifact["native_rebuild_allowed"] is False

    def test_artifact_default_validation_is_fail_closed(self):
        from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
        from pathlib import Path

        class FakeDialect:
            def model_dump(self): return {"dialect": "test", "version": "0.2.0"}
        class FakeCanonical:
            part_name = "test"; trust_level = "reference_geometry"; units = "mm"
            schema_version = "g_cad_core_v0.2"; canonical_version = "canonical_gcad_v0.2"
            raw_graph_hash = "sha256:abc"; canonical_graph_hash = "sha256:def"
            document_id = "test"
            selected_dialects = [FakeDialect()]

        artifact = build_canonical_step_artifact(
            canonical=FakeCanonical(),
            step_path=Path("/tmp/t.step"),
            metadata_path=Path("/tmp/t.json"),
        )
        # Default validation should be fail-closed (no reports → ok=False)
        assert artifact["validation"]["core_validation"]["ok"] is False
        assert artifact["validation"]["geometry_preflight"]["ok"] is False
