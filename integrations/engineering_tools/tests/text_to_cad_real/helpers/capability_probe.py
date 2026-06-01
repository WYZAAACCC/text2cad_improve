"""Capability probe — detect available dialects, primitives, and operations.

Used by tests to decide whether to expect build success or fail-closed.
"""

from __future__ import annotations

from typing import Any


def has_dialect(dialect_id: str) -> bool:
    """Check if a dialect is registered."""
    from seekflow_engineering_tools.generative_cad.dialects.registry import list_dialects
    return dialect_id in list_dialects()


def has_op(dialect_id: str, op_name: str) -> bool:
    """Check if a specific operation exists in a dialect's contract."""
    from seekflow_engineering_tools.generative_cad.dialects.registry import get_dialect
    dialect = get_dialect(dialect_id)
    if dialect is None:
        return False
    contract = dialect.contract()
    return op_name in contract.get("operations", {})


def has_any_op(dialect_ids: list[str], op_names: list[str]) -> bool:
    """Check if any of the given operations exist in any of the given dialects."""
    for did in dialect_ids:
        for op_name in op_names:
            if has_op(did, op_name):
                return True
    return False


def has_primitive(primitive_name: str) -> bool:
    """Check if a primitive is registered."""
    from seekflow_engineering_tools.geometry_primitives.registry import list_primitive_names
    return primitive_name in list_primitive_names()


def list_available_dialects() -> list[str]:
    """Return sorted list of available dialect IDs."""
    from seekflow_engineering_tools.generative_cad.dialects.registry import list_dialects
    return sorted(list_dialects())


def list_available_primitives() -> list[str]:
    """Return sorted list of available primitive names."""
    from seekflow_engineering_tools.geometry_primitives.registry import list_primitive_names
    return sorted(list_primitive_names())


def get_dialect_ops(dialect_id: str) -> dict[str, Any]:
    """Get all operations for a dialect from its contract."""
    from seekflow_engineering_tools.generative_cad.dialects.registry import get_dialect
    dialect = get_dialect(dialect_id)
    if dialect is None:
        return {}
    return dialect.contract().get("operations", {})


def capability_summary() -> dict:
    """Return a summary of all available capabilities."""
    return {
        "dialects": list_available_dialects(),
        "primitives": list_available_primitives(),
        "dialect_ops": {
            d: list(get_dialect_ops(d).keys())
            for d in list_available_dialects()
        },
        "has_thread_op": has_any_op(
            ["thread", "loft_sweep", "sweep", "sketch_extrude", "axisymmetric"],
            ["cut_internal_thread", "helical_sweep_cut", "threaded_bore"],
        ),
        "has_loft_sweep": has_dialect("loft_sweep"),
        "has_spur_gear_primitive": has_primitive("involute_spur_gear"),
    }
