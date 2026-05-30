"""M4: Artifact state machine and import gate behavior tests."""


class TestArtifactImportStateBehavior:
    def test_canonical_step_artifact_model_validates(self):
        from seekflow_engineering_tools.generative_cad.pipeline.artifact_models import CanonicalStepArtifact
        artifact = CanonicalStepArtifact(
            artifact_type="canonical_step_artifact",
            artifact_schema_version="canonical_step_artifact_v1",
            source_route="llm_skill_base",
            state="validated_reference_step",
            part_name="test", document_id="test",
            step_path="/tmp/t.step", metadata_path="/tmp/t.json",
            graph_path="/tmp/g.json",
            units="mm", trust_level="reference_geometry",
            schema_version="g_cad_core_v0.2", canonical_version="canonical_gcad_v0.2",
            raw_graph_hash="sha256:abc", canonical_graph_hash="sha256:def",
            selected_dialects=[{"dialect": "test"}],
            native_rebuild_allowed=False,
            step_import_candidate=True,
            step_import_allowed=False,
            requires_import_gate=True,
            step_sha256="sha256:abc",
            inspection={}, validation={},
        )
        assert artifact.state == "validated_reference_step"
        assert artifact.step_import_allowed is False

    def test_canonical_step_artifact_rejects_native_rebuild_true(self):
        from seekflow_engineering_tools.generative_cad.pipeline.artifact_models import CanonicalStepArtifact
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CanonicalStepArtifact(
                artifact_type="canonical_step_artifact",
                artifact_schema_version="canonical_step_artifact_v1",
                source_route="llm_skill_base",
                state="validated_reference_step",
                part_name="test", document_id="test",
                step_path="/t", metadata_path="/t", graph_path="/t",
                units="mm", trust_level="reference_geometry",
                schema_version="v", canonical_version="v",
                raw_graph_hash="sha256:a", canonical_graph_hash="sha256:b",
                selected_dialects=[],
                native_rebuild_allowed=True,
                step_import_candidate=True,
                step_import_allowed=False,
                requires_import_gate=True,
                step_sha256="sha256:a",
                inspection={}, validation={},
            )

    def test_canonical_step_artifact_rejects_extra_fields(self):
        from seekflow_engineering_tools.generative_cad.pipeline.artifact_models import CanonicalStepArtifact
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CanonicalStepArtifact(
                artifact_type="canonical_step_artifact",
                artifact_schema_version="canonical_step_artifact_v1",
                source_route="llm_skill_base",
                state="validated_reference_step",
                part_name="test", document_id="test",
                step_path="/t", metadata_path="/t", graph_path="/t",
                units="mm", trust_level="reference_geometry",
                schema_version="v", canonical_version="v",
                raw_graph_hash="sha256:a", canonical_graph_hash="sha256:b",
                selected_dialects=[],
                native_rebuild_allowed=False,
                step_import_candidate=True,
                step_import_allowed=False,
                requires_import_gate=True,
                step_sha256="sha256:a",
                inspection={}, validation={},
                extra_forbidden_field="should_fail",
            )

    def test_import_gate_result_model(self):
        from seekflow_engineering_tools.generative_cad.pipeline.import_gate_models import ImportGateResult
        result = ImportGateResult(
            ok=True, state="native_import_eligible",
            issues=[], metadata={"test": True},
            gate={"step_import_allowed": True},
        )
        assert result.ok
        assert result.state == "native_import_eligible"

    def test_artifact_state_extra_forbid(self):
        from seekflow_engineering_tools.generative_cad.pipeline.import_gate_models import ImportGateResult
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ImportGateResult(
                ok=True, issues=[], metadata={}, gate={},
                extra="no",
            )
