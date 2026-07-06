"""vNext E2E gate tests: v3 pass, v2 reject, hash mismatch, prompt paths."""

import hashlib
import json


class TestVNextE2EGate:
    """End-to-end import gate behavior tests."""

    @staticmethod
    def _v3_metadata(contract_hash: str, step_sha256: str | None = None) -> dict:
        if step_sha256 is None:
            step_sha256 = "sha256:f173fe44447b57a79ca85a732c31c5fb5fca41fcef440054a099df01e02a037b"
        return {
            "generative_metadata": {
                "metadata_version": "generative_metadata_v3",
                "source_route": "llm_skill_base",
                "schema_version": "g_cad_core_v0.2",
                "canonical_version": "canonical_gcad_v0.2",
                "trust_level": "reference_geometry",
                "part_name": "test",
                "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0", "contract_hash": contract_hash}],
                "op_versions": [{"node_id": "n1", "dialect": "axisymmetric", "op": "revolve_profile", "op_version": "1.0.0"}],
                "raw_graph_hash": "sha256:def",
                "canonical_graph_hash": "sha256:ghi",
                "paths": {
                    "canonical_ir_path": "/tmp/canonical.json",
                    "validation_seed_path": "/tmp/validation.json",
                    "step_path": "/tmp/test.step",
                    "metadata_path": "/tmp/test.metadata.json",
                },
                "runtime": {
                    "runner_version": "0.2.0",
                    "geometry_runtime": "cadquery",
                    "geometry_runtime_version": "cadquery_runtime_v1",
                },
                "artifact": {"step_sha256": step_sha256},
                "import_policy": {
                    "native_rebuild_allowed": False,
                    "requires_import_gate": True,
                    "step_import_candidate": True,
                    "step_import_allowed": False,
                },
                "operation_metrics": [],
                "degraded_features": [],
                "repair_attempts": 0,
                "warnings": [],
                "safety": {
                    "non_flight_reference_only": True, "not_airworthy": True,
                    "not_certified": True, "not_for_manufacturing": True,
                    "not_for_installation": True, "no_structural_validation": True,
                    "no_life_prediction": True,
                },
            },
            "build_warnings": [],
            "validation": {
                "core_validation": {"ok": True},
                "dialect_semantics": {"ok": True},
                "geometry_preflight": {"ok": True},
                "runtime_postconditions": {"ok": True},
                "inspection_validation": {"ok": True},
                "geometry_postcheck": {"ok": True},
            },
        }

    def test_v3_metadata_passes_gate(self, tmp_path):
        """v3 metadata with matching step_sha256 passes import gate."""
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
            validate_generative_step_artifact_for_native_import,
        )
        from seekflow_engineering_tools.generative_cad.dialects.registry import dialect_contract_hash

        ch = dialect_contract_hash("axisymmetric")
        step_file = tmp_path / "test.step"
        step_file.write_text("ISO-10303-21;")

        actual_hash = "sha256:" + hashlib.sha256(step_file.read_bytes()).hexdigest()
        metadata = self._v3_metadata(ch, step_sha256=actual_hash)
        meta_file = tmp_path / "test.metadata.json"
        meta_file.write_text(json.dumps(metadata))

        result = validate_generative_step_artifact_for_native_import(step_file, meta_file)
        assert result["ok"], f"Expected ok, got issues: {result['issues']}"
        assert result.get("state") == "native_import_eligible"

    def test_v2_metadata_rejected_by_gate(self, tmp_path):
        """v2 metadata is rejected at the production import gate."""
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
            validate_generative_step_artifact_for_native_import,
        )
        from seekflow_engineering_tools.generative_cad.dialects.registry import dialect_contract_hash

        ch = dialect_contract_hash("axisymmetric")
        v2_meta = {
            "generative_metadata": {
                "metadata_version": "generative_metadata_v2",
                "metadata_schema_minor": "2.1",
                "source_route": "llm_skill_base",
                "schema_version": "g_cad_core_v0.2",
                "canonical_version": "canonical_gcad_v0.2",
                "trust_level": "reference_geometry",
                "part_name": "test",
                "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0", "contract_hash": ch}],
                "op_versions": [{"node_id": "n1", "dialect": "axisymmetric", "op": "revolve_profile", "op_version": "1.0.0"}],
                "raw_graph_hash": "sha256:def",
                "canonical_graph_hash": "sha256:ghi",
                "runner_version": "0.2.0",
                "geometry_runtime": "cadquery",
                "operation_metrics": [],
                "degraded_features": [],
                "repair_attempts": 0,
                "warnings": [],
                "safety": {
                    "non_flight_reference_only": True, "not_airworthy": True,
                    "not_certified": True, "not_for_manufacturing": True,
                    "not_for_installation": True, "no_structural_validation": True,
                    "no_life_prediction": True,
                },
            },
            "build_warnings": [],
            "validation": {
                "core_validation": {"ok": True},
                "dialect_semantics": {"ok": True},
                "geometry_preflight": {"ok": True},
                "runtime_postconditions": {"ok": True},
                "inspection_validation": {"ok": True},
                "geometry_postcheck": {"ok": True},
            },
        }

        step_file = tmp_path / "test.step"
        step_file.write_text("ISO-10303-21;")
        meta_file = tmp_path / "test.metadata.json"
        meta_file.write_text(json.dumps(v2_meta))

        result = validate_generative_step_artifact_for_native_import(step_file, meta_file)
        assert not result["ok"]
        assert any("metadata_version_not_v3" in i.get("code", "") for i in result["issues"])

    def test_step_sha256_mismatch_rejected(self, tmp_path):
        """step_sha256 mismatch in metadata is rejected."""
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
            validate_generative_step_artifact_for_native_import,
        )
        from seekflow_engineering_tools.generative_cad.dialects.registry import dialect_contract_hash

        ch = dialect_contract_hash("axisymmetric")
        step_file = tmp_path / "test.step"
        step_file.write_text("ISO-10303-21;")

        # Use wrong hash
        metadata = self._v3_metadata(ch, step_sha256="sha256:badbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadb")
        meta_file = tmp_path / "test.metadata.json"
        meta_file.write_text(json.dumps(metadata))

        result = validate_generative_step_artifact_for_native_import(step_file, meta_file)
        assert not result["ok"]
        assert any("step_sha256_mismatch" in i.get("code", "") for i in result["issues"])

    def test_repair_prompt_has_no_double_slash_paths(self):
        """Repair prompt must not contain // placeholders."""
        from seekflow_engineering_tools.generative_cad.skills.prompts import REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/nodes//" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/components//" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/nodes/<node_id>/params/<field>" in REPAIR_PATCH_SYSTEM_PROMPT_V2
        assert "/components/<component_id>/root_node" in REPAIR_PATCH_SYSTEM_PROMPT_V2

    def test_runtime_context_has_geometry_runtime_version(self):
        """RuntimeContext exposes geometry_runtime_version property."""
        from pathlib import Path
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        ctx = RuntimeContext(
            out_step=Path("/tmp/o.step"),
            metadata_path=Path("/tmp/o.json"),
            workspace_root=Path("/tmp"),
        )
        assert hasattr(ctx, "geometry_runtime_version")
        assert ctx.geometry_runtime_version == "cadquery_runtime_v1"
