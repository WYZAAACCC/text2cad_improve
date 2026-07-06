"""Tests for staged authoring pipeline — RoutePlan → FeatureSequence → NodeParams → assemble.

All tests use mocked LLM callers (no live API required).
"""
import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_washer_route_plan():
    from seekflow_engineering_tools.generative_cad.authoring.schemas import (
        RouteDecision,
        RoutePlan,
        SelectedDialectDraft,
    )
    return RoutePlan(
        route_decision=RouteDecision.GENERATIVE_CAD_IR,
        part_intent={"object_type": "washer", "dominant_geometry": "axisymmetric"},
        selected_dialects=[
            SelectedDialectDraft(dialect="axisymmetric", version="0.2.0", reason="Rotational symmetry"),
        ],
    )


def _make_washer_feature_sequence():
    from seekflow_engineering_tools.generative_cad.authoring.schemas import (
        ComponentDraft,
        FeatureSequenceDraft,
        NodePlanDraft,
    )
    return FeatureSequenceDraft(
        components=[
            ComponentDraft(component_id="washer", owner_dialect="axisymmetric",
                           kind_hint="single_part", description="Reference washer body"),
        ],
        node_sequence=[
            NodePlanDraft(node_id="n_revolve", component_id="washer",
                          dialect="axisymmetric", op="revolve_profile",
                          op_version="1.0.0", phase="base_solid",
                          purpose="Create the base rotational solid"),
            NodePlanDraft(node_id="n_bore", component_id="washer",
                          dialect="axisymmetric", op="cut_center_bore",
                          op_version="1.0.0", phase="primary_cut",
                          purpose="Cut the center bore"),
        ],
    )


def _make_washer_node_params():
    from seekflow_engineering_tools.generative_cad.authoring.schemas import NodeParamsDraft
    return {
        "n_revolve": NodeParamsDraft(
            node_id="n_revolve", dialect="axisymmetric", op="revolve_profile",
            op_version="1.0.0",
            params={
                "axis": "Z",
                "profile_stations": [
                    {"r_mm": 40.0, "z_front_mm": 0.0, "z_rear_mm": 2.0},
                    {"r_mm": 40.0, "z_front_mm": 2.0, "z_rear_mm": 12.0},
                    {"r_mm": 14.0, "z_front_mm": 12.0, "z_rear_mm": 13.0},
                ],
            },
        ),
        "n_bore": NodeParamsDraft(
            node_id="n_bore", dialect="axisymmetric", op="cut_center_bore",
            op_version="1.0.0",
            params={"diameter_mm": 30.0, "axis": "Z", "through_all": True},
        ),
    }


# ── RoutePlan tests ──────────────────────────────────────────────────────────

class TestRoutePlan:
    def test_route_plan_requires_dialects_for_generative(self):
        from seekflow_engineering_tools.generative_cad.authoring.schemas import (
            RouteDecision,
            RoutePlan,
        )
        with pytest.raises(ValueError):
            RoutePlan(route_decision=RouteDecision.GENERATIVE_CAD_IR, selected_dialects=[])

    def test_route_plan_requires_unsupported_capabilities(self):
        from seekflow_engineering_tools.generative_cad.authoring.schemas import (
            RouteDecision,
            RoutePlan,
        )
        with pytest.raises(ValueError):
            RoutePlan(route_decision=RouteDecision.UNSUPPORTED, unsupported_capabilities=[])

    def test_route_plan_requires_clarification_questions(self):
        from seekflow_engineering_tools.generative_cad.authoring.schemas import (
            RouteDecision,
            RoutePlan,
        )
        with pytest.raises(ValueError):
            RoutePlan(route_decision=RouteDecision.NEEDS_CLARIFICATION, clarification_questions=[])

    def test_route_plan_accepts_generative_with_dialects(self):
        plan = _make_washer_route_plan()
        assert plan.route_decision.value == "generative_cad_ir"
        assert len(plan.selected_dialects) == 1

    def test_route_plan_contains_no_params(self):
        """RoutePlan must NOT have a params field (prevent field injection)."""
        plan = _make_washer_route_plan()
        assert not hasattr(plan, "params")
        assert not hasattr(plan, "nodes")

    def test_route_plan_rejects_extra_fields(self):
        from seekflow_engineering_tools.generative_cad.authoring.schemas import (
            RouteDecision,
            RoutePlan,
        )
        with pytest.raises(ValueError):
            RoutePlan(
                route_decision=RouteDecision.GENERATIVE_CAD_IR,
                selected_dialects=[{"dialect": "axisymmetric", "version": "0.2.0", "reason": "test"}],
                extra_field="should_fail",
            )


# ── FeatureSequenceDraft tests ───────────────────────────────────────────────

class TestFeatureSequenceDraft:
    def test_feature_sequence_requires_nodes(self):
        from seekflow_engineering_tools.generative_cad.authoring.schemas import (
            FeatureSequenceDraft,
        )
        with pytest.raises(ValueError):
            FeatureSequenceDraft(node_sequence=[])

    def test_feature_sequence_contains_no_params(self):
        fs = _make_washer_feature_sequence()
        for node in fs.node_sequence:
            assert not hasattr(node, "params"), f"Node {node.node_id} should not have params"

    def test_feature_sequence_rejects_unknown_component(self):
        from seekflow_engineering_tools.generative_cad.authoring.schemas import (
            FeatureSequenceDraft,
            NodePlanDraft,
        )
        with pytest.raises(ValueError, match="unknown component"):
            FeatureSequenceDraft(
                components=[],  # no components
                node_sequence=[
                    NodePlanDraft(node_id="n1", component_id="ghost",
                                  dialect="axisymmetric", op="revolve_profile",
                                  op_version="1.0.0", phase="base_solid"),
                ],
            )

    def test_feature_sequence_rejects_extra_fields(self):
        from seekflow_engineering_tools.generative_cad.authoring.schemas import (
            FeatureSequenceDraft,
        )
        with pytest.raises(ValueError):
            FeatureSequenceDraft(
                node_sequence=[{"node_id": "n1", "extra": "bad"}],
            )

    def test_feature_sequence_validates(self):
        fs = _make_washer_feature_sequence()
        assert len(fs.node_sequence) == 2
        assert fs.node_sequence[0].op == "revolve_profile"


# ── NodeParamsDraft tests ────────────────────────────────────────────────────

class TestNodeParamsDraft:
    def test_node_params_validates_shape(self):
        from seekflow_engineering_tools.generative_cad.authoring.schemas import NodeParamsDraft
        np = NodeParamsDraft(
            node_id="n1", dialect="axisymmetric", op="revolve_profile",
            op_version="1.0.0", params={"axis": "Z", "profile_stations": []},
        )
        assert np.node_id == "n1"
        assert np.params == {"axis": "Z", "profile_stations": []}

    def test_node_params_rejects_extra_fields(self):
        from seekflow_engineering_tools.generative_cad.authoring.schemas import NodeParamsDraft
        with pytest.raises(ValueError):
            NodeParamsDraft(
                node_id="n1", dialect="axisymmetric", op="revolve_profile",
                op_version="1.0.0", params={},
                extra_field="should_fail",
            )

    def test_node_params_validated_against_operation_spec(self):
        """NodeParamsDraft params must be validatable against OperationSpec.params_model."""
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        reg = default_registry()
        dialect = reg.require("axisymmetric")
        spec = dialect.get_op_spec("revolve_profile", "1.0.0")

        # Valid params
        valid_params = {
            "axis": "Z",
            "profile_stations": [
                {"r_mm": 40.0, "z_front_mm": 0.0, "z_rear_mm": 10.0},
                {"r_mm": 40.0, "z_front_mm": 10.0, "z_rear_mm": 12.0},
            ],
        }
        spec.validate_params(valid_params)  # should not raise

        # Invalid: missing required field
        with pytest.raises(Exception):
            spec.validate_params({"axis": "Z"})  # missing profile_stations

        # Invalid: wrong type
        with pytest.raises(Exception):
            spec.validate_params({"axis": "Z", "profile_stations": "not_a_list"})


# ── Context builder tests ────────────────────────────────────────────────────

class TestContextBuilder:
    def test_context_loads_only_selected_dialects(self):
        from seekflow_engineering_tools.generative_cad.authoring.context_builder import (
            build_authoring_context,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )

        plan = _make_washer_route_plan()
        ctx = build_authoring_context(
            route_plan=plan,
            dialect_registry=default_registry(),
            base_package_registry=default_base_package_registry(),
        )
        assert ctx.selected_dialects == ["axisymmetric"]
        assert "axisymmetric" in ctx.level2_usage_skills
        assert "sketch_extrude" not in ctx.level2_usage_skills, (
            "Should NOT load unselected dialect skills"
        )

    def test_context_rejects_unregistered_dialect(self):
        from seekflow_engineering_tools.generative_cad.authoring.context_builder import (
            build_authoring_context,
        )
        from seekflow_engineering_tools.generative_cad.authoring.schemas import (
            RouteDecision,
            RoutePlan,
            SelectedDialectDraft,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )

        plan = RoutePlan(
            route_decision=RouteDecision.GENERATIVE_CAD_IR,
            selected_dialects=[
                SelectedDialectDraft(dialect="nonexistent_xyz", version="0.2.0", reason="test"),
            ],
        )
        with pytest.raises(ValueError, match="not registered"):
            build_authoring_context(
                route_plan=plan,
                dialect_registry=default_registry(),
                base_package_registry=default_base_package_registry(),
            )

    def test_context_computes_hash(self):
        from seekflow_engineering_tools.generative_cad.authoring.context_builder import (
            build_authoring_context,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )

        plan = _make_washer_route_plan()
        ctx = build_authoring_context(
            route_plan=plan,
            dialect_registry=default_registry(),
            base_package_registry=default_base_package_registry(),
        )
        assert ctx.context_hash, "context_hash should be set"
        assert ctx.context_hash.startswith("sha256:")


# ── Raw assembler tests ──────────────────────────────────────────────────────

class TestRawAssembler:
    def test_assembler_fills_safety_flags(self):
        from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
            assemble_raw_gcad_document,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

        plan = _make_washer_route_plan()
        fs = _make_washer_feature_sequence()
        np_map = _make_washer_node_params()

        result = assemble_raw_gcad_document(
            user_request="Create a washer",
            route_plan=plan,
            feature_sequence=fs,
            node_params=np_map,
            dialect_registry=default_registry(),
        )

        safety = result.raw_document["safety"]
        for key, val in safety.items():
            assert val is True, f"safety.{key} must be True, got {val}"

    def test_assembler_fills_constraints(self):
        from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
            assemble_raw_gcad_document,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

        plan = _make_washer_route_plan()
        fs = _make_washer_feature_sequence()
        np_map = _make_washer_node_params()

        result = assemble_raw_gcad_document(
            user_request="Create a washer",
            route_plan=plan,
            feature_sequence=fs,
            node_params=np_map,
            dialect_registry=default_registry(),
        )

        constraints = result.raw_document["constraints"]
        assert constraints["require_step_file"] is True
        assert constraints["require_metadata_sidecar"] is True
        assert constraints["require_closed_solid"] is True
        assert constraints["expected_body_count"] >= 1

    def test_assembler_sets_reference_geometry_trust_level(self):
        from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
            assemble_raw_gcad_document,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

        plan = _make_washer_route_plan()
        fs = _make_washer_feature_sequence()
        np_map = _make_washer_node_params()

        result = assemble_raw_gcad_document(
            user_request="Create a washer",
            route_plan=plan,
            feature_sequence=fs,
            node_params=np_map,
            dialect_registry=default_registry(),
        )

        assert result.raw_document["trust_level"] == "reference_geometry"

    def test_assembler_uses_registry_versions(self):
        from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
            assemble_raw_gcad_document,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

        plan = _make_washer_route_plan()
        fs = _make_washer_feature_sequence()
        np_map = _make_washer_node_params()

        result = assemble_raw_gcad_document(
            user_request="Create a washer",
            route_plan=plan,
            feature_sequence=fs,
            node_params=np_map,
            dialect_registry=default_registry(),
        )

        # selected_dialects should use registry versions
        for sd in result.raw_document["selected_dialects"]:
            dialect = default_registry().get(sd["dialect"])
            assert sd["version"] == dialect.version, (
                f"Assembler should use registry version for {sd['dialect']}"
            )

    def test_assembler_uses_operation_spec_outputs(self):
        from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
            assemble_raw_gcad_document,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

        plan = _make_washer_route_plan()
        fs = _make_washer_feature_sequence()
        np_map = _make_washer_node_params()

        result = assemble_raw_gcad_document(
            user_request="Create a washer",
            route_plan=plan,
            feature_sequence=fs,
            node_params=np_map,
            dialect_registry=default_registry(),
        )

        # revolve_profile should output solid + frame
        revolve_node = result.raw_document["nodes"][0]
        output_types = {o["type"] for o in revolve_node["outputs"]}
        assert "solid" in output_types
        assert "frame" in output_types

    def test_assembler_wires_linear_solid_chain(self):
        from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
            assemble_raw_gcad_document,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

        plan = _make_washer_route_plan()
        fs = _make_washer_feature_sequence()
        np_map = _make_washer_node_params()

        result = assemble_raw_gcad_document(
            user_request="Create a washer",
            route_plan=plan,
            feature_sequence=fs,
            node_params=np_map,
            dialect_registry=default_registry(),
        )

        nodes = result.raw_document["nodes"]
        # First node (revolve_profile) should have empty inputs
        assert nodes[0]["inputs"] == [], "First base_solid node should have no inputs"
        # Second node should reference first node's output
        assert len(nodes[1]["inputs"]) >= 1
        assert nodes[1]["inputs"][0]["node"] == "n_revolve"

    def test_assembler_recorded_fields(self):
        from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
            assemble_raw_gcad_document,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

        plan = _make_washer_route_plan()
        fs = _make_washer_feature_sequence()
        np_map = _make_washer_node_params()

        result = assemble_raw_gcad_document(
            user_request="Create a washer",
            route_plan=plan,
            feature_sequence=fs,
            node_params=np_map,
            dialect_registry=default_registry(),
        )

        # Verify system_filled_fields records what the system filled
        assert "safety" in str(result.system_filled_fields).lower() or any(
            "safety" in f.lower() for f in result.system_filled_fields
        )
        assert "constraints" in str(result.system_filled_fields).lower() or any(
            "constraint" in f.lower() for f in result.system_filled_fields
        )

    def test_assembled_document_passes_validation(self):
        """Full assembly should produce a document that passes parse + validate."""
        from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
            assemble_raw_gcad_document,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize,
        )

        plan = _make_washer_route_plan()
        fs = _make_washer_feature_sequence()
        np_map = _make_washer_node_params()

        result = assemble_raw_gcad_document(
            user_request="Create a washer",
            route_plan=plan,
            feature_sequence=fs,
            node_params=np_map,
            dialect_registry=default_registry(),
        )

        canonical, report = validate_and_canonicalize(result.raw_document)
        assert canonical is not None, f"Canonicalize failed: {report.issues if report else 'unknown'}"
        assert report.ok, f"Validation failed: {report.issues}"
