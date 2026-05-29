"""Test that adding op params does not require core validator changes."""


def test_extended_param_validated_by_op_spec_only():
    """New params on an existing op should be validated by params_model only."""
    from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument

    # Valid params on extrude_rectangle
    data = {
        "schema_version": "g_cad_core_v0.2",
        "document_id": "ext_test",
        "part_name": "extended_params",
        "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [{"dialect": "sketch_extrude", "version": "0.2.0"}],
        "components": [{"id": "p", "owner_dialect": "sketch_extrude", "root_node": "n1"}],
        "nodes": [{
            "id": "n1", "component": "p", "dialect": "sketch_extrude",
            "op": "extrude_rectangle", "op_version": "1.0.0", "phase": "base_solid",
            "inputs": [], "outputs": [{"name": "body", "type": "solid"}],
            "params": {"width_mm": 100, "height_mm": 50, "depth_mm": 10},
            "required": True, "degradation_policy": "fail",
        }],
        "constraints": {"require_step_file": True, "require_metadata_sidecar": True, "require_closed_solid": True, "expected_body_count": 1, "max_runtime_seconds": 120},
        "safety": {"non_flight_reference_only": True, "not_airworthy": True, "not_certified": True, "not_for_manufacturing": True, "not_for_installation": True, "no_structural_validation": True, "no_life_prediction": True},
    }
    doc = RawGcadDocument.model_validate(data)
    assert doc.part_name == "extended_params"


def test_op_parameter_extension_does_not_modify_core_validator():
    """Core validation pipeline should not need changes when a new op adds params."""
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    from seekflow_engineering_tools.generative_cad.validation.structure import validate_structure
    from seekflow_engineering_tools.generative_cad.validation.registry import validate_registry

    # The core validators (structure, registry, graph, etc.) should work
    # without any knowledge of operation-specific params
    import inspect
    src = inspect.getsource(validate_structure)
    # Structure validator should not reference any params models
    assert "diameter_mm" not in src
    assert "width_mm" not in src
    assert "profile_stations" not in src

    # Registry validator should not reference specific params
    src = inspect.getsource(validate_registry)
    assert "diameter_mm" not in src
    assert "width_mm" not in src
