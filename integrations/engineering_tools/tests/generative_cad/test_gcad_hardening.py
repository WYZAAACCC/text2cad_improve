"""G-CAD v0.2.3 hardening tests: metadata mutation, mock, fallback grep, P0 checks."""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "generative_cad"


# ── P0-1: root_node structure tests ──

class TestRootNodeStructure:
    def test_missing_root_node_fails(self):
        from seekflow_engineering_tools.generative_cad.validation.structure import validate_structure
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        data["components"][0]["root_node"] = ""
        raw = RawGcadDocument.model_validate(data)
        report = validate_structure(raw)
        assert not report.ok
        assert any("missing_root_node" in i.code for i in report.issues)

    def test_root_node_not_found_fails(self):
        from seekflow_engineering_tools.generative_cad.validation.structure import validate_structure
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        data["components"][0]["root_node"] = "nonexistent"
        raw = RawGcadDocument.model_validate(data)
        report = validate_structure(raw)
        assert not report.ok
        assert any("root_node_not_found" in i.code for i in report.issues)

    def test_root_node_wrong_component_fails(self):
        from seekflow_engineering_tools.generative_cad.validation.structure import validate_structure
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
        data = json.loads(open(str(__import__('pathlib').Path(__file__).parent.parent / "fixtures" / "generative_cad" / "composed_disk_with_lugs.json")).read())
        # Point disk's root_node to lug's node
        data["components"][0]["root_node"] = "n_lug"
        raw = RawGcadDocument.model_validate(data)
        report = validate_structure(raw)
        assert not report.ok
        assert any("root_node_wrong_component" in i.code for i in report.issues)

    def test_root_node_no_outputs_fails(self):
        from seekflow_engineering_tools.generative_cad.validation.structure import validate_structure
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        data["nodes"][0]["outputs"] = []
        raw = RawGcadDocument.model_validate(data)
        report = validate_structure(raw)
        assert not report.ok
        assert any("root_node_no_outputs" in i.code for i in report.issues)

    def test_valid_root_node_passes(self):
        from seekflow_engineering_tools.generative_cad.validation.structure import validate_structure
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        raw = RawGcadDocument.model_validate(data)
        report = validate_structure(raw)
        assert report.ok


# ── P0-2: Phase dependency order tests ──

class TestPhaseOrder:
    def test_reverse_phase_fails(self):
        from seekflow_engineering_tools.generative_cad.validation.phase import validate_phase
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        # Add a cut that depends on chamfer (edge_treatment before base_solid = reverse)
        data["nodes"].append({
            "id": "n_chamfer", "component": "disk", "dialect": "axisymmetric",
            "op": "apply_safe_chamfer", "op_version": "1.0.0", "phase": "edge_treatment",
            "inputs": [{"node": "n_body", "output": "body"}],
            "outputs": [{"name": "body", "type": "solid"}],
            "params": {"distance_mm": 1.0}, "required": True, "degradation_policy": "fail",
        })
        data["nodes"].append({
            "id": "n_cut", "component": "disk", "dialect": "axisymmetric",
            "op": "cut_center_bore", "op_version": "1.0.0", "phase": "primary_cut",
            "inputs": [{"node": "n_chamfer", "output": "body"}],
            "outputs": [{"name": "body", "type": "solid"}],
            "params": {"diameter_mm": 20, "axis": "Z"}, "required": True, "degradation_policy": "fail",
        })
        raw = RawGcadDocument.model_validate(data)
        report = validate_phase(raw)
        assert not report.ok
        assert any("reverse_phase_dependency" in i.code for i in report.issues)

    def test_forward_phase_passes(self):
        from seekflow_engineering_tools.generative_cad.validation.phase import validate_phase
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        # base_solid -> primary_cut is forward
        data["nodes"].append({
            "id": "n_cut", "component": "disk", "dialect": "axisymmetric",
            "op": "cut_center_bore", "op_version": "1.0.0", "phase": "primary_cut",
            "inputs": [{"node": "n_body", "output": "body"}],
            "outputs": [{"name": "body", "type": "solid"}],
            "params": {"diameter_mm": 20, "axis": "Z"}, "required": True, "degradation_policy": "fail",
        })
        raw = RawGcadDocument.model_validate(data)
        report = validate_phase(raw)
        assert report.ok


# ── P0-3: No resolve_node_output(node.id, "body") fallback test ──

class TestNoHandlerFallback:
    def test_composition_handlers_no_self_fallback(self):
        """Verify composition handlers don't have ctx.resolve_node_output(node.id, 'body') fallback."""
        import inspect
        from seekflow_engineering_tools.generative_cad.dialects.composition import handlers as ch
        src = inspect.getsource(ch)
        assert "resolve_node_output(node.id" not in src, "Found forbidden self-referencing fallback in composition handlers"

    def test_axisymmetric_handlers_no_self_fallback(self):
        import inspect
        from seekflow_engineering_tools.generative_cad.dialects.axisymmetric import handlers as ah
        src = inspect.getsource(ah)
        assert "resolve_node_output(node.id" not in src, "Found forbidden self-referencing fallback in axisymmetric handlers"

    def test_sketch_extrude_handlers_no_self_fallback(self):
        import inspect
        from seekflow_engineering_tools.generative_cad.dialects.sketch_extrude import handlers as sh
        src = inspect.getsource(sh)
        assert "resolve_node_output(node.id" not in src, "Found forbidden self-referencing fallback in sketch_extrude handlers"


# ── P0-5: Metadata v2 mutation tests ──

class TestMetadataV2Mutation:
    def _valid_meta(self):
        from seekflow_engineering_tools.generative_cad.dialects.registry import dialect_contract_hash
        ch = dialect_contract_hash("axisymmetric")
        return {
            "generative_metadata": {
                "metadata_version": "generative_metadata_v2", "metadata_schema_minor": "2.1",
                "source_route": "llm_skill_base",
                "schema_version": "g_cad_core_v0.2", "canonical_version": "canonical_gcad_v0.2",
                "trust_level": "reference_geometry", "part_name": "test",
                "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0", "contract_hash": ch}],
                "op_versions": [{"node_id": "n1", "dialect": "axisymmetric", "op": "revolve_profile", "op_version": "1.0.0"}],
                "raw_graph_hash": "sha256:def", "canonical_graph_hash": "sha256:ghi",
                "runner_version": "0.2.0", "geometry_runtime": "cadquery",
                "operation_metrics": [], "degraded_features": [], "repair_attempts": 0, "warnings": [],
                "safety": {
                    "non_flight_reference_only": True, "not_airworthy": True, "not_certified": True,
                    "not_for_manufacturing": True, "not_for_installation": True,
                    "no_structural_validation": True, "no_life_prediction": True,
                },
            },
            "build_warnings": [],
            "validation": {
                "core_validation": {"ok": True}, "dialect_semantics": {"ok": True},
                "geometry_preflight": {"ok": True}, "runtime_postconditions": {"ok": True},
                "inspection_validation": {"ok": True},
            },
        }

    def test_valid_passes(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2
        assert validate_generative_metadata_v2(self._valid_meta())["ok"]

    def test_false_safety_rejected(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2
        m = self._valid_meta()
        m["generative_metadata"]["safety"]["not_airworthy"] = False
        assert not validate_generative_metadata_v2(m)["ok"]

    def test_missing_canonical_hash_rejected(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2
        m = self._valid_meta()
        m["generative_metadata"]["canonical_graph_hash"] = "not-a-hash"
        assert not validate_generative_metadata_v2(m)["ok"]

    def test_missing_dialects_rejected(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2
        m = self._valid_meta()
        m["generative_metadata"]["selected_dialects"] = []
        assert not validate_generative_metadata_v2(m)["ok"]

    def test_wrong_metadata_version_rejected(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2
        m = self._valid_meta()
        m["generative_metadata"]["metadata_version"] = "primitive_metadata_v1"
        assert not validate_generative_metadata_v2(m)["ok"]

    def test_trust_level_drift_rejected(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
        m = self._valid_meta()
        m["generative_metadata"]["trust_level"] = "manufacturing_ready"
        assert not validate_generative_metadata_v2(m)["ok"]


# ── P2: CadQuery mock tests ──

class TestMockCadQuery:
    def test_boolean_union_handler_with_mock(self, monkeypatch):
        """Test boolean_union handler logic with mocked cadquery."""
        import sys
        # Mock cadquery
        class MockWorkplane:
            def union(self, other):
                return MockWorkplane()
        sys.modules['cadquery'] = type(sys)('cadquery')
        sys.modules['cadquery'].Workplane = MockWorkplane

        from seekflow_engineering_tools.generative_cad.dialects.composition.handlers import handle_boolean_union
        from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode, CanonicalValueRef
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
        from pathlib import Path

        ctx = RuntimeContext(out_step=Path("/tmp/test.step"), metadata_path=Path("/tmp/test.json"), workspace_root=Path("/tmp"))
        # Pre-bind input
        ctx.object_store.put_solid(SolidHandle(id="solid:p:n1:body", component_id="p", producer_node="n1"), MockWorkplane())
        ctx.bind_node_output("n1", "body", "solid:p:n1:body")
        ctx.object_store.put_solid(SolidHandle(id="solid:p:n2:body", component_id="p", producer_node="n2"), MockWorkplane())
        ctx.bind_node_output("n2", "body", "solid:p:n2:body")

        node = CanonicalNode(
            id="n3", component="p", dialect="composition", op="boolean_union", op_version="1.0.0",
            phase="boolean",
            inputs=[
                CanonicalValueRef(producer_node="n1", output="body", resolved_type="solid"),
                CanonicalValueRef(producer_node="n2", output="body", resolved_type="solid"),
            ],
            outputs=[], params={}, typed_params={},
        )
        result = handle_boolean_union(node, ctx)
        assert "body" in result

    def test_boolean_union_requires_two_inputs(self):
        from seekflow_engineering_tools.generative_cad.dialects.composition.handlers import handle_boolean_union
        from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        from pathlib import Path

        ctx = RuntimeContext(out_step=Path("/tmp/test.step"), metadata_path=Path("/tmp/test.json"), workspace_root=Path("/tmp"))
        node = CanonicalNode(
            id="n3", component="p", dialect="composition", op="boolean_union", op_version="1.0.0",
            phase="boolean", inputs=[], outputs=[], params={}, typed_params={},
        )
        with pytest.raises(ValueError, match="exactly 2"):
            handle_boolean_union(node, ctx)


# ── P0-4: Boolean strict binary test ──

class TestBooleanStrictBinary:
    def test_union_requires_exactly_two(self):
        from seekflow_engineering_tools.generative_cad.dialects.composition.handlers import handle_boolean_union
        from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode, CanonicalValueRef
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        from pathlib import Path
        ctx = RuntimeContext(out_step=Path("/tmp/t.step"), metadata_path=Path("/tmp/t.json"), workspace_root=Path("/tmp"))
        # 1 input: should fail
        node = CanonicalNode(id="n", component="c", dialect="composition", op="boolean_union", op_version="1.0.0",
            phase="boolean", inputs=[CanonicalValueRef(producer_node="x", output="body", resolved_type="solid")],
            outputs=[], params={}, typed_params={})
        with pytest.raises(ValueError, match="exactly 2"):
            handle_boolean_union(node, ctx)

    def test_cut_requires_exactly_two(self):
        from seekflow_engineering_tools.generative_cad.dialects.composition.handlers import handle_boolean_cut
        from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode, CanonicalValueRef
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        from pathlib import Path
        ctx = RuntimeContext(out_step=Path("/tmp/t.step"), metadata_path=Path("/tmp/t.json"), workspace_root=Path("/tmp"))
        node = CanonicalNode(id="n", component="c", dialect="composition", op="boolean_cut", op_version="1.0.0",
            phase="boolean", inputs=[CanonicalValueRef(producer_node="x", output="body", resolved_type="solid")],
            outputs=[], params={}, typed_params={})
        with pytest.raises(ValueError, match="exactly 2"):
            handle_boolean_cut(node, ctx)


# ── P0-6: Artifact completeness test ──

class TestArtifactCompleteness:
    def test_artifact_has_all_required_fields(self):
        from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
        from pathlib import Path
        class FakeCanonical:
            part_name = "test"; units = "mm"; trust_level = "reference_geometry"
        artifact = build_canonical_step_artifact(
            canonical=FakeCanonical(), step_path=Path("/tmp/t.step"), metadata_path=Path("/tmp/t.json"),
            graph_path="/tmp/g.json", runner_script_path="/tmp/r.py",
        )
        assert artifact["artifact_type"] == "canonical_step_artifact"
        assert artifact["source_route"] == "llm_skill_base"
        assert artifact["step_path"] == str(Path("/tmp/t.step"))
        assert artifact["graph_path"] == "/tmp/g.json"
        assert artifact["runner_script_path"] == "/tmp/r.py"
        assert artifact["native_rebuild_allowed"] is False
        assert artifact["step_import_allowed"] is True
        assert artifact["units"] == "mm"

    def test_artifact_none_for_unavailable_paths(self):
        from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
        from pathlib import Path
        class FakeCanonical:
            part_name = "test"; units = "mm"; trust_level = "reference_geometry"
        artifact = build_canonical_step_artifact(
            canonical=FakeCanonical(), step_path=Path("/tmp/t.step"), metadata_path=Path("/tmp/t.json"),
            graph_path=None, runner_script_path=None,
        )
        assert artifact["graph_path"] is None
        assert artifact["runner_script_path"] is None


# ── Error classes tests ──

class TestErrorClasses:
    def test_errors_importable(self):
        from seekflow_engineering_tools.generative_cad.errors import (
            GenerativeCadError, ValidationFailedError, BuildFailedError,
            UnknownDialectError, UnknownOperationError, StepExportError,
        )
        e = UnknownDialectError("fake_dialect")
        assert "fake_dialect" in str(e)
        assert e.code == "UNKNOWN_DIALECT"
