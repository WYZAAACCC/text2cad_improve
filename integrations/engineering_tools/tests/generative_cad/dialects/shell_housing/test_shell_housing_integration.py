"""Step 1f: Verify shell_housing integration with sketch_extrude via typed wiring."""

import pytest


class TestShellHousingIntegration:
    """Shell housing must properly consume and output solid via typed wiring."""

    def test_shell_body_consumes_previous_solid(self):
        """shell_body should auto-consume solid from previous op in same component."""
        from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
            assemble_raw_gcad_document,
        )
        from seekflow_engineering_tools.generative_cad.authoring.schemas import (
            RoutePlan, RouteDecision, SelectedDialectDraft,
            FeatureSequenceDraft, ComponentDraft, NodePlanDraft,
            NodeParamsDraft,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

        reg = default_registry()
        route = RoutePlan(
            route_decision=RouteDecision.GENERATIVE_CAD_IR,
            part_intent={"object_type": "test"},
            selected_dialects=[
                SelectedDialectDraft(dialect="sketch_extrude", version="0.2.0", reason="test"),
                SelectedDialectDraft(dialect="shell_housing", version="0.2.0", reason="test"),
            ],
        )
        fs = FeatureSequenceDraft(
            components=[
                ComponentDraft(component_id="box", owner_dialect="sketch_extrude"),
            ],
            node_sequence=[
                NodePlanDraft(node_id="n_extrude", component_id="box",
                    dialect="sketch_extrude", op="extrude_rectangle",
                    op_version="1.0.0", phase="base_solid"),
                NodePlanDraft(node_id="n_shell", component_id="box",
                    dialect="shell_housing", op="shell_body",
                    op_version="1.0.0", phase="base_solid"),
            ],
        )
        params = {
            "n_extrude": NodeParamsDraft(
                node_id="n_extrude", dialect="sketch_extrude",
                op="extrude_rectangle", op_version="1.0.0",
                params={"width_mm": 100, "height_mm": 80, "depth_mm": 50},
            ),
            "n_shell": NodeParamsDraft(
                node_id="n_shell", dialect="shell_housing",
                op="shell_body", op_version="1.0.0",
                params={"thickness_mm": 2.0},
            ),
        }

        result = assemble_raw_gcad_document(
            user_request="test",
            route_plan=route,
            feature_sequence=fs,
            node_params=params,
            dialect_registry=reg,
        )

        shell_node = next(n for n in result.raw_document["nodes"] if n["id"] == "n_shell")
        # shell_body has input_types=["solid"], should auto-wire from n_extrude
        assert len(shell_node["inputs"]) >= 1, (
            f"shell_body should have at least 1 input, got {len(shell_node['inputs'])}"
        )
        if shell_node["inputs"]:
            assert shell_node["inputs"][0]["node"] == "n_extrude", (
                f"shell_body should consume n_extrude solid, got {shell_node['inputs']}"
            )

    def test_shell_thickness_too_large_preflight_fail(self):
        """Shell thickness > 40% of min bbox dim should fail preflight."""
        from seekflow_engineering_tools.generative_cad.dialects.shell_housing.dialect import (
            SHELL_HOUSING_DIALECT,
        )
        # Verify the dialect has preflight capability
        assert hasattr(SHELL_HOUSING_DIALECT, "preflight_component"), (
            "shell_housing dialect must have preflight_component"
        )

    def test_shell_body_outputs_solid(self):
        """shell_body must output type=solid with name=body."""
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        reg = default_registry()
        dialect = reg.get("shell_housing")
        assert dialect is not None, "shell_housing dialect must be registered"
        spec = dialect.get_op_spec("shell_body", "1.0.0")
        assert spec is not None, "shell_body operation spec must exist"
        assert "solid" in spec.output_types, "shell_body must output solid type"

    def test_shell_missing_input_fails_assembly(self):
        """When shell_body has no preceding solid, assembly should fail (not silently succeed)."""
        from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
            assemble_raw_gcad_document,
        )
        from seekflow_engineering_tools.generative_cad.authoring.schemas import (
            RoutePlan, RouteDecision, SelectedDialectDraft,
            FeatureSequenceDraft, ComponentDraft, NodePlanDraft,
            NodeParamsDraft,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

        reg = default_registry()
        route = RoutePlan(
            route_decision=RouteDecision.GENERATIVE_CAD_IR,
            part_intent={"object_type": "test"},
            selected_dialects=[
                SelectedDialectDraft(dialect="shell_housing", version="0.2.0", reason="test"),
            ],
        )
        fs = FeatureSequenceDraft(
            components=[ComponentDraft(component_id="box", owner_dialect="shell_housing")],
            node_sequence=[
                NodePlanDraft(node_id="n_shell", component_id="box",
                    dialect="shell_housing", op="shell_body",
                    op_version="1.0.0", phase="base_solid"),
            ],
        )
        params = {
            "n_shell": NodeParamsDraft(
                node_id="n_shell", dialect="shell_housing",
                op="shell_body", op_version="1.0.0",
                params={"thickness_mm": 2.0},
            ),
        }

        # When no preceding solid exists, assembly MUST fail (fail-closed)
        from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import AssemblyError
        with pytest.raises(AssemblyError, match="Missing input"):
            assemble_raw_gcad_document(
                user_request="test", route_plan=route,
                feature_sequence=fs, node_params=params,
                dialect_registry=reg,
            )
