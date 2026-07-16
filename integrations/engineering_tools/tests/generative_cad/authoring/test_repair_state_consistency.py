"""Repair Loop Phase 0 — 状态一致性回归测试 (repair_loop.md §1.1/§1.2).

Bug#1: autofix 改善但未 ok 时, 文档与诊断必须同快照提交 (不得错位);
Bug#2: LLM repair 接受后修复文档必须回写 raw_assembly.raw_document。
"""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "generative_cad"


class SequenceToolCaller:
    """Mock LLM caller — 每次 call_strict_tool 依序弹出一个预置返回值."""

    def __init__(self, returns: list[dict]):
        self._returns = list(returns)
        self.calls: list[dict] = []

    def call_strict_tool(self, **kwargs):
        self.calls.append({"tool_name": kwargs.get("tool_name", "")})
        from seekflow_engineering_tools.generative_cad.llm.provider import ToolCallResult
        args = self._returns.pop(0) if self._returns else {}
        return ToolCallResult(
            tool_name=kwargs.get("tool_name", ""),
            arguments=args,
            model="mock",
            provider="mock",
        )


def _get_registry():
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
        default_registry,
    )
    return default_registry()


def _get_base_pkg_registry():
    from seekflow_engineering_tools.generative_cad.base_packages.registry import (
        BasePackageRegistry,
    )
    bp = BasePackageRegistry()
    try:
        from seekflow_engineering_tools.generative_cad.base_packages.axisymmetric.package import (
            AXISYMMETRIC_BASE_PACKAGE,
        )
        bp.register(AXISYMMETRIC_BASE_PACKAGE)
    except Exception:
        pass
    return bp


def _make_llm_config():
    from seekflow_engineering_tools.generative_cad.llm.models import (
        AuthoringLlmConfig,
        LlmModelConfig,
    )
    return AuthoringLlmConfig(
        router=LlmModelConfig(model="mock-router"),
        author=LlmModelConfig(model="mock-author"),
        repair=LlmModelConfig(model="mock-repair"),
    )


def _route_plan_args(dialect_version: str = "0.2.0") -> dict:
    from seekflow_engineering_tools.generative_cad.authoring.schemas import (
        RouteDecision,
        RoutePlan,
        SelectedDialectDraft,
    )
    return RoutePlan(
        route_decision=RouteDecision.GENERATIVE_CAD_IR,
        part_intent={"object_type": "flange"},
        selected_dialects=[
            SelectedDialectDraft(dialect="axisymmetric", version=dialect_version,
                                 reason="test"),
        ],
    ).model_dump()


def _feature_sequence_args(n1_op_version: str = "1.0.0") -> dict:
    from seekflow_engineering_tools.generative_cad.authoring.schemas import (
        ComponentDraft,
        FeatureSequenceDraft,
        NodePlanDraft,
    )
    return FeatureSequenceDraft(
        components=[ComponentDraft(component_id="flange", owner_dialect="axisymmetric")],
        node_sequence=[
            NodePlanDraft(
                node_id="n1", component_id="flange",
                dialect="axisymmetric", op="revolve_profile",
                op_version=n1_op_version, phase="base_solid",
            ),
            NodePlanDraft(
                node_id="n2", component_id="flange",
                dialect="axisymmetric", op="cut_center_bore",
                op_version="1.0.0", phase="primary_cut",
            ),
        ],
    ).model_dump()


def _node_params_args(bore_dia_mm: float, n1_op_version: str = "1.0.0") -> list[dict]:
    from seekflow_engineering_tools.generative_cad.authoring.schemas import NodeParamsDraft
    n1 = NodeParamsDraft(
        node_id="n1", dialect="axisymmetric", op="revolve_profile",
        op_version=n1_op_version,
        params={"axis": "Z", "profile_stations": [
            {"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20},
            {"r_mm": 25, "z_front_mm": 20, "z_rear_mm": 21},
        ]},
    )
    n2 = NodeParamsDraft(
        node_id="n2", dialect="axisymmetric", op="cut_center_bore",
        op_version="1.0.0",
        params={"diameter_mm": bore_dia_mm},
    )
    return [n1.model_dump(), n2.model_dump()]


def _run_pipeline(*, bore_dia_mm: float, repair_caller=None):
    from seekflow_engineering_tools.generative_cad.authoring.pipeline import (
        generate_gcad_from_user_request,
    )
    return generate_gcad_from_user_request(
        user_request="test flange with center bore",
        llm_config=_make_llm_config(),
        dialect_registry=_get_registry(),
        base_package_registry=_get_base_pkg_registry(),
        route_caller=SequenceToolCaller([_route_plan_args()]),
        feature_sequence_caller=SequenceToolCaller([_feature_sequence_args()]),
        node_params_caller=SequenceToolCaller(_node_params_args(bore_dia_mm)),
        repair_caller=repair_caller,
    )


class TestRepairWriteback:
    """Bug#2 (§1.2): LLM repair 接受后必须回写 raw_assembly.raw_document."""

    def test_accepted_repair_written_back_to_raw_assembly(self):
        # bore dia=200 (r=100) >= 外径 50 → a002_bore_gt_outer (autofix 不可修)
        repair_caller = SequenceToolCaller([{
            "target_node": "n2",
            "target_component": None,
            "changes": [{
                "path": "/nodes/n2/params/diameter_mm",
                "old_value": 200.0,
                "new_value": 20.0,
                "reason": "bore must be smaller than outer radius",
            }],
            "reason": "shrink bore below outer radius",
            "give_up": False,
        }])
        result = _run_pipeline(bore_dia_mm=200.0, repair_caller=repair_caller)

        assert result.raw_assembly is not None
        assert result.metrics.validation_success, (
            f"repair should reach ok; failures={[f.message for f in result.failures]}"
        )
        # 关键回归 (Bug#2): 修复必须体现在 raw_assembly.raw_document
        n2 = next(n for n in result.raw_assembly.raw_document["nodes"]
                  if n["id"] == "n2")
        assert n2["params"]["diameter_mm"] == 20.0

        # 不变量: raw_document 重新验证结果与管线报告一致 (同快照)
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize_with_bundle,
        )
        _, report2, _ = validate_and_canonicalize_with_bundle(
            result.raw_assembly.raw_document)
        assert report2.ok


class TestAutofixSnapshotConsistency:
    """Bug#1 (§1.1): autofix 改善未 ok 时文档与诊断同快照提交."""

    def test_partial_autofix_keeps_doc_report_in_same_snapshot(self):
        from seekflow_engineering_tools.generative_cad.authoring.pipeline import (
            generate_gcad_from_user_request,
        )
        # 方言版本填错 (autofix _fix_dialect_names 可修, registry 停机) +
        # bore 超径 (autofix 不可修, dialect_semantics 停机)
        # → autofix 后 stage 推进但未 ok → 文档与诊断必须同快照提交
        result = generate_gcad_from_user_request(
            user_request="test flange with center bore",
            llm_config=_make_llm_config(),
            dialect_registry=_get_registry(),
            base_package_registry=_get_base_pkg_registry(),
            route_caller=SequenceToolCaller(
                [_route_plan_args(dialect_version="9.9.9")]),
            feature_sequence_caller=SequenceToolCaller([_feature_sequence_args()]),
            node_params_caller=SequenceToolCaller(_node_params_args(200.0)),
            repair_caller=None,
        )
        assert result.raw_assembly is not None
        assert not result.metrics.validation_success

        # autofix 修好 dialect 版本且质量改善 (stage 推进) → 文档必须已提交
        raw = result.raw_assembly.raw_document
        assert raw["selected_dialects"][0]["version"] != "9.9.9", (
            "autofix improvement must commit doc+report together (§1.1)"
        )

        # 不变量: raw_document 重新验证与最终诊断同快照 —
        # 剩余错误应只属 dialect_semantics (a002), 不再有 registry 错
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize_with_bundle,
        )
        _, report2, _ = validate_and_canonicalize_with_bundle(raw)
        assert not report2.ok
        codes = {i.code for i in report2.issues}
        assert "dialect_version_mismatch" not in codes
        assert any(c.startswith("a002") for c in codes)
