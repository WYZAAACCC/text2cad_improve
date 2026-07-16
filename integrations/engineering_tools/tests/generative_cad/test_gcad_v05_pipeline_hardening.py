"""v0.5 pipeline hardening tests — no optional canonical validators, stages_run, stage=complete."""

import inspect
import json
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures" / "generative_cad"


def _load_minimal_axisymmetric():
    data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
    return data


class TestPipelineHardening:
    def test_canonical_validators_are_not_lazy_optional(self):
        """Canonical validators must be registered without lazy fallback.

        v0.7: validator 登记迁移至 validation_kernel/legacy_adapter.py,
        源检查对象随之更新; 防护意图不变 — 缺失即硬错, 禁止 ImportError 静默降级。
        """
        from seekflow_engineering_tools.generative_cad.validation_kernel import legacy_adapter
        src = inspect.getsource(legacy_adapter)
        assert "_get_canonical_stages" not in src
        assert "except ImportError" not in src
        assert "validate_dialect_semantics" in src
        assert "validate_geometry_preflight" in src
        # 运行时保证: 默认注册表必含这两条 canonical 规则
        from seekflow_engineering_tools.generative_cad.validation_kernel import (
            default_rule_registry,
        )
        ids = default_rule_registry().list_rule_ids()
        assert "core.legacy.dialect_semantics" in ids
        assert "core.legacy.geometry_preflight" in ids

    def test_success_report_stage_is_complete(self):
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize_with_bundle,
        )
        canonical, report, bundle = validate_and_canonicalize_with_bundle(_load_minimal_axisymmetric())
        assert canonical is not None
        assert report.ok
        assert report.stage == "complete"
        assert "dialect_semantics" in report.stages_run
        assert "geometry_preflight" in report.stages_run
        assert bundle.ok
        assert "dialect_semantics" in bundle.canonical_stage_reports
        assert "geometry_preflight" in bundle.canonical_stage_reports

    def test_validate_and_canonicalize_backward_compat(self):
        from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
        canonical, report = validate_and_canonicalize(_load_minimal_axisymmetric())
        assert canonical is not None
        assert report.ok
        assert report.stage == "complete"

    def test_valid_axisymmetric_passes_all_stages(self):
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize_with_bundle,
        )
        canonical, report, bundle = validate_and_canonicalize_with_bundle(_load_minimal_axisymmetric())
        assert canonical is not None
        assert report.ok
        expected_stages = [
            "structure", "registry", "params", "ownership", "graph",
            "typecheck", "phase", "composition", "safety",
            "canonicalize", "dialect_semantics", "geometry_preflight",
        ]
        for stage in expected_stages:
            assert stage in report.stages_run, f"missing stage: {stage}"
