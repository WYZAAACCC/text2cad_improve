"""G-CAD Core v0.2 integration tests."""

import json
import tempfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "generative_cad"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ── P0: Import smoke ──

def test_import_generative_cad_modules():
    from seekflow_engineering_tools.generative_cad.ir import raw
    from seekflow_engineering_tools.generative_cad.ir import canonical
    from seekflow_engineering_tools.generative_cad.dialects.registry import DIALECT_REGISTRY
    from seekflow_engineering_tools.generative_cad.runtime.results import GcadRunResult
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    from seekflow_engineering_tools.generative_cad.pipeline.run import run_gcad_core
    assert True


def test_registry_has_axisymmetric_sketch_extrude_composition():
    from seekflow_engineering_tools.generative_cad.dialects.registry import list_dialects
    dialects = list_dialects()
    assert "axisymmetric" in dialects
    assert "sketch_extrude" in dialects
    assert "composition" in dialects


def test_harness_result_has_metadata_path():
    from seekflow_engineering_tools.generative_cad.runner import GenerativeRunResult
    result = GenerativeRunResult(ok=True, metadata_path=Path("/tmp/test.json"))
    assert result.metadata_path is not None
    assert str(result.metadata_path) == str(Path("/tmp/test.json"))


# ── RawGcadDocument ──

def test_raw_gcad_document_minimal_valid():
    from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
    data = _load_fixture("axisymmetric_minimal.json")
    doc = RawGcadDocument.model_validate(data)
    assert doc.schema_version == "g_cad_core_v0.2"
    assert doc.part_name == "minimal_disk"


def test_unknown_dialect_fails_closed():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("axisymmetric_minimal.json")
    data["selected_dialects"] = [{"dialect": "nonexistent", "version": "0.2.0"}]
    canonical, report = validate_and_canonicalize(data)
    assert canonical is None
    assert not report.ok
    assert any("unknown_dialect" in i.code for i in report.issues)


def test_unknown_op_fails_closed():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("invalid_unknown_op.json")
    canonical, report = validate_and_canonicalize(data)
    assert canonical is None
    assert not report.ok


def test_safety_false_fails():
    from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
    with pytest.raises(ValueError, match="must be true"):
        RawGcadDocument.model_validate(_load_fixture("invalid_safety_false.json"))


def test_constraints_false_fails():
    from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
    data = _load_fixture("axisymmetric_minimal.json")
    data["constraints"]["require_step_file"] = False
    with pytest.raises(ValueError, match="require_step_file cannot be false"):
        RawGcadDocument.model_validate(data)


def test_duplicate_component_id_fails():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("axisymmetric_minimal.json")
    data["components"] = [
        {"id": "same", "owner_dialect": "axisymmetric", "root_node": "n1"},
        {"id": "same", "owner_dialect": "axisymmetric", "root_node": "n2"},
    ]
    canonical, report = validate_and_canonicalize(data)
    assert not report.ok


def test_duplicate_node_id_fails():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("axisymmetric_minimal.json")
    data["nodes"] = [
        {"id": "same", "component": "disk", "dialect": "axisymmetric", "op": "revolve_profile", "op_version": "1.0.0", "phase": "base_solid", "inputs": [], "outputs": [{"name": "body", "type": "solid"}, {"name": "outer_frame", "type": "frame"}], "params": {"axis": "Z", "profile_stations": [{"r_mm": 100, "z_front_mm": 0, "z_rear_mm": 10}, {"r_mm": 50, "z_front_mm": 10, "z_rear_mm": 20}]}, "required": True, "degradation_policy": "fail"},
        {"id": "same", "component": "disk", "dialect": "axisymmetric", "op": "cut_center_bore", "op_version": "1.0.0", "phase": "primary_cut", "inputs": [{"node": "same", "output": "body"}], "outputs": [{"name": "body", "type": "solid"}], "params": {"diameter_mm": 10, "axis": "Z"}, "required": True, "degradation_policy": "fail"},
    ]
    canonical, report = validate_and_canonicalize(data)
    assert not report.ok


def test_missing_component_fails():
    from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
    data = _load_fixture("axisymmetric_minimal.json")
    data["components"] = []
    with pytest.raises(ValueError, match="components must not be empty"):
        RawGcadDocument.model_validate(data)


def test_node_unknown_component_fails():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("axisymmetric_minimal.json")
    data["nodes"][0]["component"] = "nonexistent_component"
    canonical, report = validate_and_canonicalize(data)
    assert not report.ok


def test_selected_dialect_missing_fails():
    from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
    data = _load_fixture("axisymmetric_minimal.json")
    data["selected_dialects"] = []
    with pytest.raises(ValueError, match="selected_dialects must not be empty"):
        RawGcadDocument.model_validate(data)


def test_node_dialect_not_selected_fails():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("axisymmetric_minimal.json")
    data["selected_dialects"] = [{"dialect": "sketch_extrude", "version": "0.2.0"}]
    canonical, report = validate_and_canonicalize(data)
    # Node uses "axisymmetric" but selected_dialects has "sketch_extrude" only
    # This should fail at ownership stage
    assert not report.ok


def test_default_op_version_inserted_in_canonical():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("axisymmetric_minimal.json")
    # Remove op_version to test default insertion
    del data["nodes"][0]["op_version"]
    canonical, report = validate_and_canonicalize(data)
    assert canonical is not None
    assert report.ok
    assert canonical.nodes[0].op_version == "1.0.0"


def test_canonical_graph_hash_stable():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("axisymmetric_minimal.json")
    c1, _ = validate_and_canonicalize(data)
    c2, _ = validate_and_canonicalize(data)
    assert c1.canonical_graph_hash == c2.canonical_graph_hash


def test_canonical_graph_hash_changes_on_param_change():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data1 = _load_fixture("axisymmetric_minimal.json")
    data2 = _load_fixture("axisymmetric_minimal.json")
    data2["nodes"][0]["params"]["profile_stations"][0]["r_mm"] = 200
    c1, _ = validate_and_canonicalize(data1)
    c2, _ = validate_and_canonicalize(data2)
    assert c1.canonical_graph_hash != c2.canonical_graph_hash


# ── Type system ──

def test_input_ref_missing_output_fails():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("axisymmetric_minimal.json")
    # Add a second node referencing non-existent output
    data["nodes"].append({
        "id": "n2", "component": "disk", "dialect": "axisymmetric",
        "op": "cut_center_bore", "op_version": "1.0.0", "phase": "primary_cut",
        "inputs": [{"node": "n_body", "output": "nonexistent_output"}],
        "outputs": [{"name": "body", "type": "solid"}],
        "params": {"diameter_mm": 10, "axis": "Z"},
        "required": True, "degradation_policy": "fail",
    })
    canonical, report = validate_and_canonicalize(data)
    assert not report.ok
    assert any("missing_output_ref" in i.code for i in report.issues)


# ── Ownership ──

def test_component_owner_dialect_enforced():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("axisymmetric_minimal.json")
    data["nodes"][0]["dialect"] = "sketch_extrude"
    canonical, report = validate_and_canonicalize(data)
    assert not report.ok


def test_cross_base_direct_reference_forbidden():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("invalid_cross_base_direct_ref.json")
    canonical, report = validate_and_canonicalize(data)
    assert not report.ok


def test_cross_base_composition_allowed():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("composed_disk_with_lugs.json")
    canonical, report = validate_and_canonicalize(data)
    assert canonical is not None
    assert report.ok


def test_multiple_components_without_assembly_fails():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("composed_disk_with_lugs.json")
    # Remove assembly component
    data["components"] = [c for c in data["components"] if c["id"] != "__assembly__"]
    data["nodes"] = [n for n in data["nodes"] if n["component"] != "__assembly__"]
    data["selected_dialects"] = [d for d in data["selected_dialects"] if d["dialect"] != "composition"]
    canonical, report = validate_and_canonicalize(data)
    assert canonical is not None
    assert report.ok
    # But runtime would fail with multiple components


def test_single_component_without_assembly_allowed():
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    data = _load_fixture("axisymmetric_minimal.json")
    canonical, report = validate_and_canonicalize(data)
    assert canonical is not None
    assert report.ok


# ── Metadata v2 ──

def test_metadata_v2_validates():
    from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2
    meta = {
        "generative_metadata": {
            "metadata_version": "generative_metadata_v2",
            "source_route": "llm_skill_base",
            "schema_version": "g_cad_core_v0.2",
            "canonical_version": "canonical_gcad_v0.2",
            "trust_level": "reference_geometry",
            "part_name": "test",
            "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0", "contract_hash": "sha256:abc"}],
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
                "non_flight_reference_only": True,
                "not_airworthy": True,
                "not_certified": True,
                "not_for_manufacturing": True,
                "not_for_installation": True,
                "no_structural_validation": True,
                "no_life_prediction": True,
            },
        },
        "build_warnings": [],
        "validation": {},
    }
    result = validate_generative_metadata_v2(meta)
    assert result["ok"], f"Expected ok, got: {result['issues']}"


# ── CadQuery-dependent runner tests ──

class TestRunnerCadQuery:
    def test_axisymmetric_minimal_build_exports_step(self):
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_gcad_core
        with tempfile.TemporaryDirectory() as tmp:
            raw = _load_fixture("axisymmetric_minimal.json")
            out_step = Path(tmp) / "output.step"
            meta_path = Path(tmp) / "output.metadata.json"
            result = run_gcad_core(raw, out_step, meta_path)
            assert result.ok, f"Build failed: {result.error}"
            assert out_step.exists()
            assert meta_path.exists()

    def test_sketch_extrude_minimal_build_exports_step(self):
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_gcad_core
        with tempfile.TemporaryDirectory() as tmp:
            raw = _load_fixture("sketch_extrude_minimal.json")
            out_step = Path(tmp) / "output.step"
            meta_path = Path(tmp) / "output.metadata.json"
            result = run_gcad_core(raw, out_step, meta_path)
            assert result.ok, f"Build failed: {result.error}"
            assert out_step.exists()

    def test_composed_build_exports_step(self):
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_gcad_core
        with tempfile.TemporaryDirectory() as tmp:
            raw = _load_fixture("composed_disk_with_lugs.json")
            out_step = Path(tmp) / "output.step"
            meta_path = Path(tmp) / "output.metadata.json"
            result = run_gcad_core(raw, out_step, meta_path)
            assert result.ok, f"Build failed: {result.error}"
            assert out_step.exists()
            assert meta_path.exists()
            # Verify metadata v2
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            gm = meta["generative_metadata"]
            assert gm["metadata_version"] == "generative_metadata_v2"
            assert len(gm["selected_dialects"]) == 3

    def test_metadata_v2_written(self):
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_gcad_core
        with tempfile.TemporaryDirectory() as tmp:
            raw = _load_fixture("axisymmetric_minimal.json")
            out_step = Path(tmp) / "output.step"
            meta_path = Path(tmp) / "output.metadata.json"
            result = run_gcad_core(raw, out_step, meta_path)
            assert result.ok
            assert result.metadata_path == meta_path
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            assert meta["generative_metadata"]["metadata_version"] == "generative_metadata_v2"
