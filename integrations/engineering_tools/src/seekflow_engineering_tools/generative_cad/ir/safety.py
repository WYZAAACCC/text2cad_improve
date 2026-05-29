"""Safety flag enforcement for G-CAD Core IR."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.raw import RawSafety


def safety_all_true(safety: RawSafety) -> bool:
    d = safety.model_dump()
    return all(v is True for v in d.values())
