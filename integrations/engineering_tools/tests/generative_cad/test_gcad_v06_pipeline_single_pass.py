"""v0.6: ensure validators run exactly once."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures" / "generative_cad"


class TestPipelineSinglePass:
    def test_pipeline_runs_each_validator_once(self):
        """v0.7: 通过独立 RuleRegistry 注入计数 validator (原 monkeypatch RAW_STAGES 方式
        已随 pipeline 迁移至 validation_kernel 而更新, 测试意图不变: 每个 validator 恰好跑一次)."""
        from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport
        from seekflow_engineering_tools.generative_cad.validation_kernel import (
            RuleManifest, RuleRegistry, ValidationStage, run_validation,
        )
        from seekflow_engineering_tools.generative_cad.validation_kernel.legacy_adapter import (
            register_legacy_core_rules,
        )

        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        calls = {"structure": 0}

        def fake_structure(raw):
            calls["structure"] += 1
            return ValidationReport.ok_report("structure")

        reg = RuleRegistry()
        register_legacy_core_rules(reg)
        # 用计数 validator 替换 structure 规则 (注册在独立 registry, 不污染默认单例)
        reg._rules["core.legacy.structure"].evaluate = fake_structure  # test-only override
        reg.freeze()

        run_validation(data, registry=reg)
        assert calls["structure"] == 1, f"structure validator ran {calls['structure']} times, expected 1"


class TestNoDoubleRun:
    def test_valid_axisymmetric_single_pass(self):
        """End-to-end: valid axisymmetric doc passes with single-pass pipeline."""
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize_with_bundle,
        )
        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        canonical, report, bundle = validate_and_canonicalize_with_bundle(data)
        assert canonical is not None
        assert report.ok
        assert report.stage == "complete"
        assert bundle.ok
