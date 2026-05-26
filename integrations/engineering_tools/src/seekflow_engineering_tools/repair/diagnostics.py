"""Structured diagnostics and repair prompt generation."""

from __future__ import annotations

import json


def build_repair_prompt(
    spec: dict, result: dict, validation_report: dict
) -> str:
    """Generate a structured repair prompt for LLM-based auto-fix.

    Produces context the LLM can use to correct a CAD-IR that failed
    compilation, execution, or validation.
    """
    return f"""The CAD build failed or validation failed.

Original CAD-IR:
{json.dumps(spec, ensure_ascii=False, indent=2)}

Execution result:
{json.dumps(result, ensure_ascii=False, indent=2)}

Validation report:
{json.dumps(validation_report, ensure_ascii=False, indent=2)}

Return ONLY a corrected CAD-IR JSON. Do not write backend API code.
"""
