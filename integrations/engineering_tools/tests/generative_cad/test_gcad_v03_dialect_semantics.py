"""v0.3 dialect semantics validation tests."""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "generative_cad"


class TestAxisymmetricDialectSemantics:
    def test_axisymmetric_requires_revolve_profile_base_solid(self):
        from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize

        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        canonical, report = validate_and_canonicalize(data)
        assert canonical is not None
        assert report.ok

    def test_axisymmetric_rejects_multiple_base_solid_nodes(self):
        from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize

        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        data["nodes"].append({
            "id": "n_body2", "component": "disk", "dialect": "axisymmetric",
            "op": "revolve_profile", "op_version": "1.0.0", "phase": "base_solid",
            "inputs": [],
            "outputs": [{"name": "body", "type": "solid"}, {"name": "outer_frame", "type": "frame"}],
            "params": {"axis": "Z", "profile_stations": [
                {"r_mm": 30, "z_front_mm": 0, "z_rear_mm": 5},
                {"r_mm": 20, "z_front_mm": 5, "z_rear_mm": 10},
            ]},
            "required": True, "degradation_policy": "fail",
        })
        canonical, report = validate_and_canonicalize(data)
        assert not report.ok
        codes = {i.code for i in report.issues}
        assert "axisymmetric_base_solid_count" in codes


class TestSketchExtrudeDialectSemantics:
    def test_sketch_extrude_requires_extrude_rectangle_base_solid(self):
        from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize

        data = json.loads((FIXTURES / "sketch_extrude_minimal.json").read_text(encoding="utf-8"))
        canonical, report = validate_and_canonicalize(data)
        assert canonical is not None
        assert report.ok

    def test_sketch_extrude_rejects_non_extrude_base_op(self):
        from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize

        data = json.loads((FIXTURES / "sketch_extrude_minimal.json").read_text(encoding="utf-8"))
        # Change base_solid op to cut_hole - this will fail at params or dialect_semantics
        data["nodes"][0]["op"] = "cut_hole"
        # cut_hole requires inputs and different params, so it will fail validation
        canonical, report = validate_and_canonicalize(data)
        assert not report.ok


class TestCompositionDialectSemantics:
    def test_composition_component_must_be_assembly(self):
        from seekflow_engineering_tools.generative_cad.dialects.composition.dialect import COMPOSITION_DIALECT
        from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalComponent

        comp = CanonicalComponent(id="not_assembly", owner_dialect="composition",
                                  kind_hint=None, root_node="n1")
        report = COMPOSITION_DIALECT.validate_component(comp, [])
        assert not report.ok
        assert any("composition_not_assembly" in i.code for i in report.issues)

    def test_boolean_cut_requires_two_inputs_in_semantics(self):
        from seekflow_engineering_tools.generative_cad.dialects.composition.dialect import COMPOSITION_DIALECT
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalComponent, CanonicalNode, CanonicalValueRef,
        )

        comp = CanonicalComponent(id="__assembly__", owner_dialect="composition",
                                  kind_hint=None, root_node="n2")
        nodes = [
            CanonicalNode(id="n1", component="__assembly__", dialect="composition",
                          op="boolean_cut", op_version="1.0.0", phase="boolean",
                          inputs=[
                              CanonicalValueRef(producer_node="other", output="body", resolved_type="solid"),
                          ],
                          outputs=[], params={}, typed_params={}),
            CanonicalNode(id="n2", component="__assembly__", dialect="composition",
                          op="boolean_union", op_version="1.0.0", phase="boolean",
                          inputs=[
                              CanonicalValueRef(producer_node="other1", output="body", resolved_type="solid"),
                              CanonicalValueRef(producer_node="other2", output="body", resolved_type="solid"),
                          ],
                          outputs=[], params={}, typed_params={}),
        ]
        report = COMPOSITION_DIALECT.validate_component(comp, nodes)
        assert not report.ok
        assert any("comp_boolean_cut_binary" in i.code for i in report.issues)
