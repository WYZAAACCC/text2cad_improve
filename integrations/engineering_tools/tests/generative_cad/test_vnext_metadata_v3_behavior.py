"""M3: MetadataProofV3 behavior tests."""

import json


class TestMetadataV3Behavior:
    @staticmethod
    def _minimal_canonical():
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalGcadDocument, CanonicalComponent, CanonicalNode,
            CanonicalSelectedDialect, CanonicalValueDecl,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        ch = default_registry().contract_hash("axisymmetric")
        return CanonicalGcadDocument(
            schema_version="g_cad_core_v0.2",
            canonical_version="canonical_gcad_v0.2",
            document_id="test", part_name="test",
            units="mm", trust_level="reference_geometry",
            raw_graph_hash="sha256:abc",
            canonical_graph_hash="sha256:def",
            selected_dialects=[
                CanonicalSelectedDialect(dialect="axisymmetric", version="0.2.0", contract_hash=ch)
            ],
            components=[
                CanonicalComponent(id="disk", owner_dialect="axisymmetric", root_node="n_body")
            ],
            nodes=[
                CanonicalNode(
                    id="n_body", component="disk", dialect="axisymmetric",
                    op="revolve_profile", op_version="1.0.0", phase="base_solid",
                    outputs=[CanonicalValueDecl(name="body", type="solid", value_id="v1")],
                    required=True,
                ),
            ],
            constraints={
                "require_step_file": True, "require_metadata_sidecar": True,
                "require_closed_solid": True, "expected_body_count": 1,
                "max_runtime_seconds": 120,
            },
            safety={
                "non_flight_reference_only": True, "not_airworthy": True,
                "not_certified": True, "not_for_manufacturing": True,
                "not_for_installation": True, "no_structural_validation": True,
                "no_life_prediction": True,
            },
        )

    @staticmethod
    def _runtime_context(tmp_path):
        from pathlib import Path
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        return RuntimeContext(
            out_step=tmp_path / "out.step",
            metadata_path=tmp_path / "out.metadata.json",
            workspace_root=tmp_path,
        )

    def test_metadata_v3_builds_with_paths(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata_v3 import build_generative_metadata_v3
        from pathlib import Path
        canonical = self._minimal_canonical()
        ctx = self._runtime_context(tmp_path)
        validation = {
            "core_validation": {"ok": True},
            "dialect_semantics": {"ok": True},
            "geometry_preflight": {"ok": True},
            "runtime_postconditions": {"ok": True},
            "inspection_validation": {"ok": True},
        }
        step_path = tmp_path / "test.step"
        step_path.write_text("ISO-10303-21;")
        result = build_generative_metadata_v3(
            canonical=canonical, ctx=ctx, validation=validation,
            canonical_ir_path=Path("/tmp/canonical.json"),
            validation_seed_path=Path("/tmp/validation.json"),
            step_path=step_path,
            metadata_path=tmp_path / "test.metadata.json",
        )
        gm = result["generative_metadata"]
        assert gm["metadata_version"] == "generative_metadata_v3"
        assert gm["paths"]["step_path"] == str(step_path)
        assert gm["runtime"]["geometry_runtime_version"] == "cadquery_runtime_v1"
        assert gm["import_policy"]["native_rebuild_allowed"] is False
        assert gm["import_policy"]["step_import_allowed"] is False

    def test_metadata_v3_requires_import_policy(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata_v3 import validate_generative_metadata_v3
        result = validate_generative_metadata_v3({"generative_metadata": {}})
        assert not result["ok"]
        assert any("import_policy" in i["code"] for i in result["issues"])

    def test_metadata_v3_rejects_native_rebuild_true(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata_v3 import validate_generative_metadata_v3
        metadata = {
            "generative_metadata": {
                "metadata_version": "generative_metadata_v3",
                "import_policy": {
                    "native_rebuild_allowed": True,
                    "requires_import_gate": True,
                    "step_import_allowed": False,
                },
                "paths": {},
                "runtime": {},
                "artifact": {"step_sha256": "sha256:abc123"},
                "safety": {
                    "non_flight_reference_only": True, "not_airworthy": True,
                    "not_certified": True, "not_for_manufacturing": True,
                    "not_for_installation": True, "no_structural_validation": True,
                    "no_life_prediction": True,
                },
                "validation": {},
            },
            "validation": {},
        }
        result = validate_generative_metadata_v3(metadata)
        assert not result["ok"]
        assert any("native_rebuild" in i["code"] for i in result["issues"])

    def test_metadata_v3_missing_validation_stage_fails_closed(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata_v3 import validate_generative_metadata_v3
        metadata = {
            "generative_metadata": {
                "metadata_version": "generative_metadata_v3",
                "source_route": "llm_skill_base",
                "trust_level": "reference_geometry",
                "selected_dialects": [],
                "raw_graph_hash": "sha256:abc",
                "canonical_graph_hash": "sha256:def",
                "paths": {
                    "canonical_ir_path": "/tmp/c.json",
                    "validation_seed_path": "/tmp/v.json",
                    "step_path": "/tmp/s.step",
                    "metadata_path": "/tmp/m.json",
                },
                "runtime": {
                    "runner_version": "0.2.0",
                    "geometry_runtime": "cadquery",
                    "geometry_runtime_version": "cadquery_runtime_v1",
                },
                "artifact": {"step_sha256": "sha256:abc123"},
                "import_policy": {
                    "native_rebuild_allowed": False,
                    "requires_import_gate": True,
                    "step_import_allowed": False,
                },
                "safety": {
                    "non_flight_reference_only": True, "not_airworthy": True,
                    "not_certified": True, "not_for_manufacturing": True,
                    "not_for_installation": True, "no_structural_validation": True,
                    "no_life_prediction": True,
                },
            },
            "validation": {},
        }
        result = validate_generative_metadata_v3(metadata, require_validation_ok=True)
        assert not result["ok"]
        assert any("core_validation" in i["code"] for i in result["issues"])

    def test_metadata_v3_contract_hash_mismatch_fails(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata_v3 import validate_generative_metadata_v3
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        registry = default_registry()
        metadata = {
            "generative_metadata": {
                "metadata_version": "generative_metadata_v3",
                "source_route": "llm_skill_base",
                "trust_level": "reference_geometry",
                "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0", "contract_hash": "sha256:bad"}],
                "raw_graph_hash": "sha256:abc",
                "canonical_graph_hash": "sha256:def",
                "paths": {"canonical_ir_path": "/t", "validation_seed_path": "/t", "step_path": "/t", "metadata_path": "/t"},
                "runtime": {"runner_version": "0", "geometry_runtime": "cq", "geometry_runtime_version": "1"},
                "artifact": {"step_sha256": "sha256:abc123"},
                "import_policy": {"native_rebuild_allowed": False, "requires_import_gate": True, "step_import_allowed": False},
                "safety": {k: True for k in ["non_flight_reference_only", "not_airworthy", "not_certified", "not_for_manufacturing", "not_for_installation", "no_structural_validation", "no_life_prediction"]},
            },
            "validation": {},
        }
        result = validate_generative_metadata_v3(metadata, registry=registry)
        assert not result["ok"]
        assert any("contract_hash" in i["code"] for i in result["issues"])
