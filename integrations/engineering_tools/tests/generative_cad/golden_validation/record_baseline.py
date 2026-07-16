"""录制 golden 行为基线 — 用当前 validate + autofix 实现生成 expected.json.

用法 (仅在建立/刷新基线时运行, 刷新必须有充分理由并 review diff):
  PYTHONPATH=src python tests/generative_cad/golden_validation/record_baseline.py
"""
from __future__ import annotations
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def snapshot_behavior(raw_doc: dict) -> dict:
    """对一个 llm_raw 文档跑当前 validate→autofix→revalidate 链, 产出可比对快照."""
    from seekflow_engineering_tools.generative_cad.validation.pipeline import (
        validate_and_canonicalize_with_bundle,
    )
    from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import (
        auto_fix_with_report,
    )
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
        default_registry,
    )

    def report_snap(report) -> dict:
        return {
            "ok": report.ok,
            "stage": report.stage,
            "stages_run": list(report.stages_run),
            # message 不锁定 (可能含非关键动态内容); code/stage/severity/path 是行为契约
            "issues": [
                {"stage": i.stage, "code": i.code, "severity": i.severity, "path": i.path}
                for i in report.issues
            ],
        }

    snap: dict = {}

    canonical, report, _bundle = validate_and_canonicalize_with_bundle(raw_doc)
    snap["validate"] = report_snap(report)
    snap["canonical_graph_hash"] = canonical.canonical_graph_hash if canonical else None

    fixed, af = auto_fix_with_report(raw_doc, default_registry())
    snap["autofix"] = {
        "applied": af.applied,
        "rule_ids": [e.rule_id for e in af.entries],
        "before_hash": af.before_hash,
        "after_hash": af.after_hash,
    }

    canonical2, report2, _b2 = validate_and_canonicalize_with_bundle(fixed)
    snap["revalidate_after_fix"] = report_snap(report2)
    snap["canonical_graph_hash_after_fix"] = (
        canonical2.canonical_graph_hash if canonical2 else None
    )
    return snap


def main() -> None:
    for case_dir in sorted(FIXTURES.iterdir()):
        raw_path = case_dir / "llm_raw.json"
        if not raw_path.exists():
            continue
        raw_doc = json.loads(raw_path.read_text(encoding="utf-8"))
        snap = snapshot_behavior(raw_doc)
        out = case_dir / "expected.json"
        out.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{case_dir.name}: validate.ok={snap['validate']['ok']} "
              f"stage={snap['validate']['stage']} "
              f"autofix.applied={snap['autofix']['applied']} "
              f"revalidate.ok={snap['revalidate_after_fix']['ok']}")


if __name__ == "__main__":
    main()
