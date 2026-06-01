"""Report writer for text-to-CAD test runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_report(results: list[Any], output_dir: Path) -> Path:
    """Write test run report as JSON.

    Args:
        results: List of TextToCadResult objects.
        output_dir: Directory to write report files.

    Returns:
        Path to the report JSON file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = []
    passed = 0
    failed = 0
    errors = 0

    for r in results:
        case_ok = _evaluate_case(r)
        case_summary = {
            "case_id": r.case_id,
            "ok": case_ok,
            "expected_outcome": r.expected_outcome,
            "actual_route": r.actual_route,
            "step_path": str(r.step_path) if r.step_path else None,
            "metadata_path": str(r.metadata_path) if r.metadata_path else None,
            "artifact_path": str(r.artifact_path) if r.artifact_path else None,
            "import_gate_ok": r.ok,
            "validation_stages": getattr(r, "validation_stages", {}),
            "repair_attempts": r.repair_attempts,
            "warnings": r.warnings,
            "error_stage": r.error_stage,
            "error_code": r.error_code,
            "error": r.error,
            "passed": case_ok,
        }
        cases.append(case_summary)

        if case_ok:
            passed += 1
        elif r.error:
            errors += 1
        else:
            failed += 1

    report = {
        "report_version": "1.0.0",
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "cases": cases,
    }

    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report_path


def _evaluate_case(r) -> bool:
    """Evaluate whether a test case result matches its expected outcome."""
    expected = r.expected_outcome

    if expected == "should_build":
        return r.ok and r.step_exists

    if expected == "should_route_to_primitive":
        return r.ok and r.actual_route == "deterministic_primitive"

    if expected == "should_fail_closed":
        # fail_closed means: result.ok is False, OR route is unsupported
        return (not r.ok) or r.actual_route == "unsupported"

    if expected == "capability_dependent":
        # For capability-dependent tests, we pass if:
        # - Build succeeded (capability exists) OR
        # - Build failed AND error code indicates missing capability
        if r.ok:
            return True
        capability_codes = {
            "unsupported_capability", "dialect_not_available",
            "unknown_op_forbidden", "thread_not_supported",
            "unsupported", "unknown_dialect",
        }
        return r.error_code in capability_codes

    return False
