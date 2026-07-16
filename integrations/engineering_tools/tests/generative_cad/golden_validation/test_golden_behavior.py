"""Golden 行为基线回归测试 — validate + autofix 行为冻结.

Phase 0 (docs/text2cad_validation_autofix_refactor_guide_v1.md §17):
在 validation_kernel / repair_kernel 重构期间, 每一步都必须保持这些真实
LLM 输出样例的 validate→autofix→revalidate 行为完全不变。

基线由 record_baseline.py 用重构前实现录制。刷新基线必须有充分理由并 review。
"""
from __future__ import annotations
import json
from pathlib import Path

import pytest

from tests.generative_cad.golden_validation.record_baseline import snapshot_behavior

FIXTURES = Path(__file__).parent / "fixtures"
CASES = sorted(p.name for p in FIXTURES.iterdir() if (p / "expected.json").exists())


@pytest.mark.parametrize("case", CASES)
def test_golden_behavior_frozen(case: str) -> None:
    case_dir = FIXTURES / case
    raw_doc = json.loads((case_dir / "llm_raw.json").read_text(encoding="utf-8"))
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))

    actual = snapshot_behavior(raw_doc)

    assert actual["validate"] == expected["validate"], f"{case}: validate 行为漂移"
    assert actual["canonical_graph_hash"] == expected["canonical_graph_hash"]
    assert actual["autofix"] == expected["autofix"], f"{case}: autofix 行为漂移"
    assert actual["revalidate_after_fix"] == expected["revalidate_after_fix"], (
        f"{case}: 修复后再验证行为漂移")
    assert actual["canonical_graph_hash_after_fix"] == expected["canonical_graph_hash_after_fix"]


def test_cases_cover_pass_and_fail() -> None:
    """基线必须同时覆盖 修复后通过 与 修复后仍失败 两类样例."""
    outcomes = set()
    for case in CASES:
        exp = json.loads((FIXTURES / case / "expected.json").read_text(encoding="utf-8"))
        outcomes.add(exp["revalidate_after_fix"]["ok"])
    assert outcomes == {True, False}
