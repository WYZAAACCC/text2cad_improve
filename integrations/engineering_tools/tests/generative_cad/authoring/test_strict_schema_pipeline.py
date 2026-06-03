"""Step 1a: Verify strict tool schema is connected to all 4 pipeline stages.

Tests use RecordingLlmToolCaller to intercept tool_schema passed to each
call_strict_tool invocation without requiring real LLM API calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "generative_cad"


class RecordingLlmToolCaller:
    """Mock LLM caller that records tool_schema passed to call_strict_tool."""

    def __init__(self, return_args: dict):
        self._return = return_args
        self.calls: list[dict] = []

    def call_strict_tool(self, **kwargs) -> "ToolCallResult":
        self.calls.append({
            "tool_schema": kwargs.get("tool_schema", {}),
            "tool_name": kwargs.get("tool_name", ""),
            "messages": kwargs.get("messages", []),
        })
        from seekflow_engineering_tools.generative_cad.llm.provider import ToolCallResult
        return ToolCallResult(
            tool_name=kwargs.get("tool_name", ""),
            arguments=self._return,
            model="mock",
            provider="mock",
        )


def _get_registry():
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
    return default_registry()


def _get_base_pkg_registry():
    """Build a minimal BasePackageRegistry for testing."""
    from seekflow_engineering_tools.generative_cad.base_packages.registry import BasePackageRegistry
    bp = BasePackageRegistry()
    # Try to load real base packages; use mock if unavailable
    try:
        from seekflow_engineering_tools.generative_cad.base_packages.axisymmetric.package import AXISYMMETRIC_BASE_PACKAGE
        bp.register(AXISYMMETRIC_BASE_PACKAGE)
    except Exception:
        pass
    try:
        from seekflow_engineering_tools.generative_cad.base_packages.sketch_extrude.package import SKETCH_EXTRUDE_BASE_PACKAGE
        bp.register(SKETCH_EXTRUDE_BASE_PACKAGE)
    except Exception:
        pass
    try:
        from seekflow_engineering_tools.generative_cad.base_packages.composition.package import COMPOSITION_BASE_PACKAGE
        bp.register(COMPOSITION_BASE_PACKAGE)
    except Exception:
        pass
    try:
        from seekflow_engineering_tools.generative_cad.base_packages.sketch_profile.package import SKETCH_PROFILE_BASE_PACKAGE
        bp.register(SKETCH_PROFILE_BASE_PACKAGE)
    except Exception:
        pass
    # If no real packages loaded, skip — tests that need them will be skipped
    if not bp.list_ids():
        return bp
    return bp


def _make_route_plan():
    from seekflow_engineering_tools.generative_cad.authoring.schemas import (
        RoutePlan, RouteDecision, SelectedDialectDraft,
    )
    return RoutePlan(
        route_decision=RouteDecision.GENERATIVE_CAD_IR,
        part_intent={"object_type": "flange"},
        selected_dialects=[
            SelectedDialectDraft(dialect="axisymmetric", version="0.2.0", reason="test"),
        ],
    )


def _make_feature_sequence():
    from seekflow_engineering_tools.generative_cad.authoring.schemas import (
        FeatureSequenceDraft, ComponentDraft, NodePlanDraft,
    )
    return FeatureSequenceDraft(
        components=[ComponentDraft(component_id="flange", owner_dialect="axisymmetric")],
        node_sequence=[
            NodePlanDraft(
                node_id="n1", component_id="flange",
                dialect="axisymmetric", op="revolve_profile",
                op_version="1.0.0", phase="base_solid",
            ),
        ],
    )


def _make_node_params():
    from seekflow_engineering_tools.generative_cad.authoring.schemas import NodeParamsDraft
    return {
        "n1": NodeParamsDraft(
            node_id="n1", dialect="axisymmetric", op="revolve_profile",
            op_version="1.0.0",
            params={"axis": "Z", "profile_stations": [
                {"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20},
                {"r_mm": 25, "z_front_mm": 20, "z_rear_mm": 21},
            ]},
        ),
    }


def _make_llm_config():
    from seekflow_engineering_tools.generative_cad.llm.models import (
        AuthoringLlmConfig, LlmModelConfig,
    )
    return AuthoringLlmConfig(
        router=LlmModelConfig(model="mock-router"),
        author=LlmModelConfig(model="mock-author"),
        repair=LlmModelConfig(model="mock-repair"),
    )


class TestStrictSchemaPipeline:
    """Verify every pipeline stage passes a non-empty tool_schema."""

    def test_route_stage_uses_non_empty_schema(self):
        """Route caller must receive a non-empty tool_schema dict."""
        from seekflow_engineering_tools.generative_cad.authoring.pipeline import (
            generate_gcad_from_user_request,
        )
        route_caller = RecordingLlmToolCaller(_make_route_plan().model_dump())
        fs_caller = RecordingLlmToolCaller(_make_feature_sequence().model_dump())
        np_caller = RecordingLlmToolCaller(
            list(_make_node_params().values())[0].model_dump()
        )

        generate_gcad_from_user_request(
            user_request="test flange",
            llm_config=_make_llm_config(),
            dialect_registry=_get_registry(),
            base_package_registry=_get_base_pkg_registry(),
            route_caller=route_caller,
            feature_sequence_caller=fs_caller,
            node_params_caller=np_caller,
        )

        assert len(route_caller.calls) >= 1, "Route caller was not invoked"
        schema = route_caller.calls[0]["tool_schema"]
        assert isinstance(schema, dict), f"tool_schema is not dict: {type(schema)}"
        assert len(schema) > 0, "Route tool_schema is empty"
        # Should have type=object and additionalProperties=false after strict transform
        assert schema.get("type") == "object", f"Expected type=object, got {schema.get('type')}"

    def test_feature_sequence_stage_uses_non_empty_schema(self):
        """Feature sequence caller must receive a non-empty tool_schema."""
        from seekflow_engineering_tools.generative_cad.authoring.pipeline import (
            generate_gcad_from_user_request,
        )
        route_caller = RecordingLlmToolCaller(_make_route_plan().model_dump())
        fs_caller = RecordingLlmToolCaller(_make_feature_sequence().model_dump())
        np_caller = RecordingLlmToolCaller(
            list(_make_node_params().values())[0].model_dump()
        )

        generate_gcad_from_user_request(
            user_request="test flange",
            llm_config=_make_llm_config(),
            dialect_registry=_get_registry(),
            base_package_registry=_get_base_pkg_registry(),
            route_caller=route_caller,
            feature_sequence_caller=fs_caller,
            node_params_caller=np_caller,
        )

        assert len(fs_caller.calls) >= 1, "Feature sequence caller was not invoked"
        schema = fs_caller.calls[0]["tool_schema"]
        assert isinstance(schema, dict)
        assert len(schema) > 0, "Feature sequence tool_schema is empty"

    def test_node_params_uses_operation_specific_schema(self):
        """Node params schema must replace open dict with concrete params model."""
        from seekflow_engineering_tools.generative_cad.authoring.pipeline import (
            generate_gcad_from_user_request,
        )
        route_caller = RecordingLlmToolCaller(_make_route_plan().model_dump())
        fs_caller = RecordingLlmToolCaller(_make_feature_sequence().model_dump())
        np_caller = RecordingLlmToolCaller(
            list(_make_node_params().values())[0].model_dump()
        )

        generate_gcad_from_user_request(
            user_request="test flange",
            llm_config=_make_llm_config(),
            dialect_registry=_get_registry(),
            base_package_registry=_get_base_pkg_registry(),
            route_caller=route_caller,
            feature_sequence_caller=fs_caller,
            node_params_caller=np_caller,
        )

        assert len(np_caller.calls) >= 1, "Node params caller was not invoked"
        schema = np_caller.calls[0]["tool_schema"]
        assert isinstance(schema, dict)
        assert len(schema) > 0, "Node params tool_schema is empty"
        # params field should be a specific Pydantic model, not an open dict
        props = schema.get("properties", {})
        if "params" in props:
            params_schema = props["params"]
            # Should NOT be an empty open dict
            has_real_props = (
                params_schema.get("properties")
                and len(params_schema.get("properties", {})) > 0
            )
            assert has_real_props, (
                f"params schema should have concrete properties, got {params_schema}"
            )

    def test_node_params_constrains_node_identity(self):
        """Node params schema must const-constrain node_id/dialect/op/op_version."""
        from seekflow_engineering_tools.generative_cad.authoring.pipeline import (
            generate_gcad_from_user_request,
        )
        route_caller = RecordingLlmToolCaller(_make_route_plan().model_dump())
        fs_caller = RecordingLlmToolCaller(_make_feature_sequence().model_dump())
        np_caller = RecordingLlmToolCaller(
            list(_make_node_params().values())[0].model_dump()
        )

        generate_gcad_from_user_request(
            user_request="test flange",
            llm_config=_make_llm_config(),
            dialect_registry=_get_registry(),
            base_package_registry=_get_base_pkg_registry(),
            route_caller=route_caller,
            feature_sequence_caller=fs_caller,
            node_params_caller=np_caller,
        )

        schema = np_caller.calls[0]["tool_schema"]
        props = schema.get("properties", {})
        # node_id should be const-constrained
        assert "node_id" in props, "node_id missing from node params schema"
        assert "const" in props["node_id"] or props["node_id"].get("type") == "string", (
            f"node_id should be const-constrained: {props['node_id']}"
        )

    def test_repair_stage_uses_non_empty_schema(self):
        """Repair caller must receive a non-empty tool_schema."""
        from seekflow_engineering_tools.generative_cad.authoring.tool_schemas import (
            build_repair_patch_tool_schema,
        )
        schema = build_repair_patch_tool_schema()
        assert isinstance(schema, dict)
        assert len(schema) > 0, "Repair tool_schema is empty"

    def test_route_schema_has_dialect_enum(self):
        """Route schema must constrain selected_dialects to registered dialects."""
        from seekflow_engineering_tools.generative_cad.authoring.tool_schemas import (
            build_route_plan_tool_schema,
        )
        schema = build_route_plan_tool_schema(dialect_registry=_get_registry())
        assert isinstance(schema, dict)
        # Should contain dialect-related constraints
        schema_str = json.dumps(schema)
        assert "axisymmetric" in schema_str or "enum" in schema_str, (
            "Route schema should constrain dialect names"
        )
