"""v0.3 composition validation tests — C001-C008 rules."""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "generative_cad"


def _base_doc():
    return json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))


class TestCompositionValidation:
    def test_multiple_components_without_assembly_fails(self):
        """C001: multiple non-assembly components require __assembly__."""
        from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize

        data = _base_doc()
        # Add a second non-assembly component without __assembly__
        data["components"].append({
            "id": "comp_extra", "owner_dialect": "axisymmetric", "root_node": "n_extra"
        })
        data["nodes"].append({
            "id": "n_extra", "component": "comp_extra", "dialect": "axisymmetric",
            "op": "revolve_profile", "op_version": "1.0.0", "phase": "base_solid",
            "inputs": [],
            "outputs": [{"name": "body", "type": "solid"}, {"name": "outer_frame", "type": "frame"}],
            "params": {"axis": "Z", "profile_stations": [
                {"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 5},
                {"r_mm": 30, "z_front_mm": 5, "z_rear_mm": 10},
            ]},
            "required": True, "degradation_policy": "fail",
        })

        canonical, report = validate_and_canonicalize(data)
        assert canonical is None
        assert not report.ok
        codes = {i.code for i in report.issues}
        assert "multiple_components_require_assembly" in codes

    def test_assembly_owner_must_be_composition(self):
        """C002: __assembly__ must have owner_dialect=composition."""
        from seekflow_engineering_tools.generative_cad.validation.composition import validate_composition_requirements
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument

        data = _base_doc()
        data["components"].append({
            "id": "__assembly__", "owner_dialect": "axisymmetric", "root_node": "n_asm"
        })
        data["nodes"].append({
            "id": "n_asm", "component": "__assembly__", "dialect": "axisymmetric",
            "op": "revolve_profile", "op_version": "1.0.0", "phase": "base_solid",
            "inputs": [],
            "outputs": [{"name": "body", "type": "solid"}],
            "params": {"axis": "Z", "profile_stations": [
                {"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 5},
                {"r_mm": 30, "z_front_mm": 5, "z_rear_mm": 10},
            ]},
            "required": True, "degradation_policy": "fail",
        })
        raw = RawGcadDocument.model_validate(data)
        report = validate_composition_requirements(raw)
        assert not report.ok
        assert any("assembly_owner_must_be_composition" in i.code for i in report.issues)

    def test_assembly_root_node_required(self):
        """C004: __assembly__ must have explicit root_node."""
        from seekflow_engineering_tools.generative_cad.validation.composition import validate_composition_requirements
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument

        data = _base_doc()
        data["components"].append({
            "id": "__assembly__", "owner_dialect": "composition", "root_node": ""
        })
        raw = RawGcadDocument.model_validate(data)
        report = validate_composition_requirements(raw)
        assert not report.ok
        assert any("assembly_missing_root_node" in i.code for i in report.issues)

    def test_assembly_root_must_output_body_solid(self):
        """C005: __assembly__ root_node must output body:solid."""
        from seekflow_engineering_tools.generative_cad.validation.composition import validate_composition_requirements
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument

        data = _base_doc()
        data["components"].append({
            "id": "__assembly__", "owner_dialect": "composition", "root_node": "n_asm"
        })
        data["nodes"].append({
            "id": "n_asm", "component": "__assembly__", "dialect": "composition",
            "op": "translate_solid", "op_version": "1.0.0", "phase": "transform",
            "inputs": [{"node": "n_body", "output": "body"}],
            "outputs": [{"name": "frame", "type": "frame"}],
            "params": {"x_mm": 0, "y_mm": 0, "z_mm": 10},
            "required": True, "degradation_policy": "fail",
        })
        raw = RawGcadDocument.model_validate(data)
        report = validate_composition_requirements(raw)
        assert not report.ok
        assert any("assembly_root_must_output_body_solid" in i.code for i in report.issues)

    def test_component_root_must_output_body_solid(self):
        """C006: non-assembly component root_node must output body:solid."""
        from seekflow_engineering_tools.generative_cad.validation.composition import validate_composition_requirements
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument

        data = _base_doc()
        # Change the root node to not output body:solid
        data["nodes"][0]["outputs"] = [{"name": "frame", "type": "frame"}]
        raw = RawGcadDocument.model_validate(data)
        report = validate_composition_requirements(raw)
        assert not report.ok
        assert any("component_root_must_output_body_solid" in i.code for i in report.issues)

    def test_single_component_without_assembly_allowed(self):
        """C007: single non-assembly component without __assembly__ is fine."""
        from seekflow_engineering_tools.generative_cad.validation.composition import validate_composition_requirements
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument

        data = _base_doc()
        raw = RawGcadDocument.model_validate(data)
        report = validate_composition_requirements(raw)
        assert report.ok

    def test_assembly_node_must_use_composition(self):
        """C008: assembly nodes must use composition dialect."""
        from seekflow_engineering_tools.generative_cad.validation.composition import validate_composition_requirements
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument

        data = _base_doc()
        data["components"].append({
            "id": "__assembly__", "owner_dialect": "composition", "root_node": "n_asm"
        })
        data["nodes"].append({
            "id": "n_asm", "component": "__assembly__", "dialect": "axisymmetric",
            "op": "revolve_profile", "op_version": "1.0.0", "phase": "base_solid",
            "inputs": [],
            "outputs": [{"name": "body", "type": "solid"}],
            "params": {"axis": "Z", "profile_stations": [
                {"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 5},
                {"r_mm": 30, "z_front_mm": 5, "z_rear_mm": 10},
            ]},
            "required": True, "degradation_policy": "fail",
        })
        raw = RawGcadDocument.model_validate(data)
        report = validate_composition_requirements(raw)
        assert not report.ok
        assert any("assembly_node_must_use_composition" in i.code for i in report.issues)
