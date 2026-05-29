"""Dual-route isolation tests: prove primitive and generative paths remain separate."""

import pytest


class TestPrimitivePathIntact:
    def test_cad_part_spec_still_exists(self):
        from seekflow_engineering_tools.ir.cad import CADPartSpec
        spec = CADPartSpec.model_validate({
            "name": "test", "units": "mm", "target_backend": ["cadquery"],
            "features": [{"id": "f1", "type": "recipe", "recipe_name": "box", "parameters": {"length_mm": 100, "width_mm": 50, "height_mm": 30}}],
        })
        assert spec.name == "test"

    def test_cad_part_spec_rejects_gcad_fields(self):
        from seekflow_engineering_tools.ir.cad import CADPartSpec
        with pytest.raises(ValueError):
            CADPartSpec.model_validate({
                "name": "test", "units": "mm", "target_backend": ["cadquery"],
                "features": [{"id": "f1", "type": "generative", "graph": {}}],
            })

    def test_raw_gcad_rejects_cad_part_spec_features(self):
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
        with pytest.raises(ValueError):
            RawGcadDocument.model_validate({
                "schema_version": "g_cad_core_v0.2", "document_id": "test", "part_name": "test",
                "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0"}],
                "components": [{"id": "c1", "owner_dialect": "axisymmetric", "root_node": "n1"}],
                "nodes": [{"id": "n1", "component": "c1", "dialect": "axisymmetric", "op": "revolve_profile", "op_version": "1.0.0", "phase": "base_solid", "inputs": [], "outputs": [{"name": "body", "type": "solid"}, {"name": "outer_frame", "type": "frame"}], "params": {"axis": "Z", "profile_stations": [{"r_mm": 100, "z_front_mm": 0, "z_rear_mm": 10}, {"r_mm": 50, "z_front_mm": 10, "z_rear_mm": 20}]}, "required": True, "degradation_policy": "fail"}],
                "features": [{"type": "primitive"}],
            })


class TestPrimitiveRegistryClean:
    def test_primitive_compiler_registry_no_dialects(self):
        from seekflow_engineering_tools.cadquery_backend.primitive_compiler import PRIMITIVE_COMPILERS
        for name in ["axisymmetric", "sketch_extrude", "composition"]:
            assert name not in PRIMITIVE_COMPILERS, f"{name!r} leaked into PRIMITIVE_COMPILERS"

    def test_primitive_registry_no_dialects(self):
        from seekflow_engineering_tools.geometry_primitives.registry import PRIMITIVE_REGISTRY
        for name in ["axisymmetric", "sketch_extrude", "composition"]:
            assert name not in PRIMITIVE_REGISTRY, f"{name!r} leaked into PRIMITIVE_REGISTRY"

    def test_dialect_registry_no_primitives(self):
        from seekflow_engineering_tools.generative_cad.dialects.registry import DIALECT_REGISTRY
        for name in ["involute_spur_gear", "axisymmetric_turbine_disk"]:
            assert name not in DIALECT_REGISTRY, f"{name!r} leaked into DIALECT_REGISTRY"

    def test_capabilities_stable_primitives_no_dialects(self):
        from seekflow_engineering_tools.capabilities.registry import CAPABILITIES
        cq = CAPABILITIES.get("cadquery", {}).get("stable_primitives", [])
        for name in ["axisymmetric", "sketch_extrude", "composition"]:
            assert name not in cq, f"{name!r} leaked into cadquery stable_primitives"


class TestMetadataSchemasDistinct:
    def test_primitive_metadata_is_v1(self):
        """Primitive metadata uses primitive_metadata_v1."""
        from seekflow_engineering_tools.mechanical_validation.primitive_metadata import validate_primitive_metadata_v1
        meta = {
            "primitive_metadata": {
                "axisymmetric_turbine_disk": {
                    "primitive": "axisymmetric_turbine_disk",
                    "metadata_version": "primitive_metadata_v1",
                    "kernel": "cadquery_turbine_disk_reference_v6",
                    "parameters": {}, "reference_dimensions": {}, "warnings": [],
                    "safety": {"non_flight_reference_only": True, "not_airworthy": True, "not_certified": True, "not_for_manufacturing": True, "not_for_installation": True, "no_structural_validation": True, "no_life_prediction": True},
                }
            },
            "build_warnings": [],
            "validation": {},
        }
        # validate_primitive_metadata_v1 takes (primitive_name, metadata) kwargs
        result = validate_primitive_metadata_v1(primitive_name="axisymmetric_turbine_disk", metadata=meta["primitive_metadata"]["axisymmetric_turbine_disk"])
        assert result["ok"]

    def test_generative_metadata_is_v2(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2
        meta = {
            "generative_metadata": {
                "metadata_version": "generative_metadata_v2", "source_route": "llm_skill_base",
                "schema_version": "g_cad_core_v0.2", "canonical_version": "canonical_gcad_v0.2",
                "trust_level": "reference_geometry", "part_name": "test",
                "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0", "contract_hash": "sha256:abc"}],
                "op_versions": [],
                "raw_graph_hash": "sha256:def", "canonical_graph_hash": "sha256:ghi",
                "runner_version": "0.2.0", "geometry_runtime": "cadquery",
                "operation_metrics": [], "degraded_features": [], "repair_attempts": 0, "warnings": [],
                "safety": {"non_flight_reference_only": True, "not_airworthy": True, "not_certified": True, "not_for_manufacturing": True, "not_for_installation": True, "no_structural_validation": True, "no_life_prediction": True},
            },
            "build_warnings": [],
            "validation": {"core_validation": {}, "geometry_preflight": {}, "inspection_validation": {}},
        }
        result = validate_generative_metadata_v2(meta)
        assert result["ok"], f"Expected ok, got: {result['issues']}"


class TestSharedInspectionAllowed:
    def test_inspect_step_with_cadquery_importable(self):
        from seekflow_engineering_tools.cadquery_backend.inspector import inspect_step_with_cadquery
        assert callable(inspect_step_with_cadquery)
