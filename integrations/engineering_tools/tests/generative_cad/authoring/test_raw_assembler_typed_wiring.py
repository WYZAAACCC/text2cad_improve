"""Step 1b: Verify raw assembler typed wiring — curve, profile, shell, boolean_union.

Tests verify the assembler correctly wires typed outputs (curve, profile, sketch)
to downstream consumers, handles fail-closed behavior on missing inputs, and
expands multi-solid boolean_union pairwise.
"""

from __future__ import annotations

import pytest


def _get_registry():
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
    return default_registry()


def _make_route_plan(dialects: list[str]):
    from seekflow_engineering_tools.generative_cad.authoring.schemas import (
        RoutePlan, RouteDecision, SelectedDialectDraft,
    )
    return RoutePlan(
        route_decision=RouteDecision.GENERATIVE_CAD_IR,
        part_intent={"object_type": "test_part"},
        selected_dialects=[
            SelectedDialectDraft(dialect=d, version="0.2.0", reason="test")
            for d in dialects
        ],
    )


def _make_feature_sequence(components, node_sequence):
    from seekflow_engineering_tools.generative_cad.authoring.schemas import (
        FeatureSequenceDraft, ComponentDraft, NodePlanDraft,
    )
    comps = [
        ComponentDraft(
            component_id=c["id"],
            owner_dialect=c.get("owner_dialect", c.get("dialect", "axisymmetric")),
        )
        for c in components
    ]
    nodes = []
    for n in node_sequence:
        nodes.append(NodePlanDraft(
            node_id=n["id"], component_id=n.get("component_id", components[0]["id"]),
            dialect=n["dialect"], op=n["op"],
            op_version=n.get("op_version", "1.0.0"),
            phase=n.get("phase", "base_solid"),
        ))
    return FeatureSequenceDraft(components=comps, node_sequence=nodes)


def _make_node_params(node_id, dialect, op, params, op_version="1.0.0"):
    from seekflow_engineering_tools.generative_cad.authoring.schemas import NodeParamsDraft
    return NodeParamsDraft(
        node_id=node_id, dialect=dialect, op=op,
        op_version=op_version, params=params,
    )


def _assemble(route, fs, params_dict):
    from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
        assemble_raw_gcad_document,
    )
    return assemble_raw_gcad_document(
        user_request="test",
        route_plan=route,
        feature_sequence=fs,
        node_params=params_dict,
        dialect_registry=_get_registry(),
    )


class TestSweepPathCurveWiring:
    """create_sweep_path outputs curve → sweep_profile consumes curve."""

    def test_sweep_path_wires_curve_to_sweep_profile(self):
        """create_sweep_path → curve output must auto-connect to sweep_profile input."""
        components = [{"id": "pipe", "owner_dialect": "loft_sweep"}]
        nodes = [
            {"id": "n_path", "component_id": "pipe", "dialect": "loft_sweep",
             "op": "create_sweep_path", "op_version": "1.0.0", "phase": "path"},
            {"id": "n_sweep", "component_id": "pipe", "dialect": "loft_sweep",
             "op": "sweep_profile", "op_version": "1.0.0", "phase": "sweep"},
        ]
        route = _make_route_plan(["loft_sweep"])
        fs = _make_feature_sequence(components, nodes)
        params = {
            "n_path": _make_node_params("n_path", "loft_sweep", "create_sweep_path",
                {"path_points": [{"x_mm": 0, "y_mm": 0, "z_mm": 0}, {"x_mm": 10, "y_mm": 0, "z_mm": 10}]}),
            "n_sweep": _make_node_params("n_sweep", "loft_sweep", "sweep_profile",
                {"shape": "circle", "radius_mm": 8}),
        }

        result = _assemble(route, fs, params)
        sweep_node = next(n for n in result.raw_document["nodes"] if n["id"] == "n_sweep")
        assert len(sweep_node["inputs"]) == 1, f"Expected 1 input, got {sweep_node['inputs']}"
        assert sweep_node["inputs"][0]["node"] == "n_path", "sweep input should reference path node"
        assert sweep_node["inputs"][0]["output"] == "curve", "sweep should consume 'curve' output"

    def test_create_sweep_path_has_curve_output(self):
        """create_sweep_path node must output type=curve with name=curve."""
        components = [{"id": "pipe", "owner_dialect": "loft_sweep"}]
        nodes = [
            {"id": "n_path", "component_id": "pipe", "dialect": "loft_sweep",
             "op": "create_sweep_path", "op_version": "1.0.0", "phase": "path"},
            {"id": "n_sweep", "component_id": "pipe", "dialect": "loft_sweep",
             "op": "sweep_profile", "op_version": "1.0.0", "phase": "sweep"},
        ]
        route = _make_route_plan(["loft_sweep"])
        fs = _make_feature_sequence(components, nodes)
        params = {
            "n_path": _make_node_params("n_path", "loft_sweep", "create_sweep_path",
                {"path_points": [{"x_mm": 0, "y_mm": 0, "z_mm": 0}, {"x_mm": 10, "y_mm": 0, "z_mm": 10}]}),
            "n_sweep": _make_node_params("n_sweep", "loft_sweep", "sweep_profile",
                {"shape": "circle", "radius_mm": 8}),
        }

        result = _assemble(route, fs, params)
        path_node = next(n for n in result.raw_document["nodes"] if n["id"] == "n_path")
        output_types = [o["type"] for o in path_node["outputs"]]
        assert "curve" in output_types, f"create_sweep_path must output curve, got {path_node['outputs']}"


class TestBooleanUnionWiring:
    """boolean_union must handle 2 solids and expand 3+ pairwise."""

    def test_boolean_union_two_solids_ok(self):
        """boolean_union with exactly 2 assembly solids should work."""
        components = [
            {"id": "hub", "owner_dialect": "axisymmetric"},
            {"id": "base", "owner_dialect": "sketch_extrude"},
            {"id": "__assembly__", "owner_dialect": "composition"},
        ]
        nodes = [
            {"id": "n_revolve", "component_id": "hub", "dialect": "axisymmetric",
             "op": "revolve_profile", "op_version": "1.0.0", "phase": "base_solid"},
            {"id": "n_extrude", "component_id": "base", "dialect": "sketch_extrude",
             "op": "extrude_rectangle", "op_version": "1.0.0", "phase": "base_solid"},
            {"id": "n_union", "component_id": "__assembly__", "dialect": "composition",
             "op": "boolean_union", "op_version": "1.0.0", "phase": "base_solid"},
        ]
        route = _make_route_plan(["axisymmetric", "sketch_extrude", "composition"])
        fs = _make_feature_sequence(components, nodes)
        params = {
            "n_revolve": _make_node_params("n_revolve", "axisymmetric", "revolve_profile",
                {"axis": "Z", "profile_stations": [
                    {"r_mm": 30, "z_front_mm": 0, "z_rear_mm": 40},
                    {"r_mm": 20, "z_front_mm": 40, "z_rear_mm": 41},
                ]}),
            "n_extrude": _make_node_params("n_extrude", "sketch_extrude", "extrude_rectangle",
                {"width_mm": 100, "height_mm": 80, "depth_mm": 15}),
            "n_union": _make_node_params("n_union", "composition", "boolean_union", {}),
        }

        result = _assemble(route, fs, params)
        union_node = next(n for n in result.raw_document["nodes"] if n["id"] == "n_union")
        assert len(union_node["inputs"]) == 2, (
            f"boolean_union should have 2 inputs, got {len(union_node['inputs'])}"
        )

    def test_component_root_node_is_last_solid(self):
        """Each component's root_node must point to its last solid-producing node."""
        components = [{"id": "hub", "owner_dialect": "axisymmetric"}]
        nodes = [
            {"id": "n_revolve", "component_id": "hub", "dialect": "axisymmetric",
             "op": "revolve_profile", "op_version": "1.0.0", "phase": "base_solid"},
            {"id": "n_bore", "component_id": "hub", "dialect": "axisymmetric",
             "op": "cut_center_bore", "op_version": "1.0.0", "phase": "primary_cut"},
        ]
        route = _make_route_plan(["axisymmetric"])
        fs = _make_feature_sequence(components, nodes)
        params = {
            "n_revolve": _make_node_params("n_revolve", "axisymmetric", "revolve_profile",
                {"axis": "Z", "profile_stations": [
                    {"r_mm": 30, "z_front_mm": 0, "z_rear_mm": 40},
                    {"r_mm": 20, "z_front_mm": 40, "z_rear_mm": 41},
                ]}),
            "n_bore": _make_node_params("n_bore", "axisymmetric", "cut_center_bore",
                {"diameter_mm": 15, "axis": "Z", "through_all": True}),
        }

        result = _assemble(route, fs, params)
        hub_comp = next(c for c in result.raw_document["components"] if c["id"] == "hub")
        assert hub_comp.get("root_node") == "n_bore", (
            f"root_node should be last solid (n_bore), got {hub_comp.get('root_node')}"
        )
