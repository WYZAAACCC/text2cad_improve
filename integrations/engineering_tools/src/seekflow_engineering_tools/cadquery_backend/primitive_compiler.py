"""Compile PrimitiveFeature specs into CadQuery Python code.

Primitives route to deterministic geometry kernels — NEVER to LLM-generated code.
"""

from __future__ import annotations

from typing import Callable

PrimitiveCompileHandler = Callable[[object], list[str]]
"""A handler that takes a PrimitiveFeature and returns CadQuery code lines."""

PRIMITIVE_COMPILERS: dict[str, PrimitiveCompileHandler] = {}


class PrimitiveCompileError(RuntimeError):
    pass


def register_primitive_compiler(name: str, handler: PrimitiveCompileHandler) -> None:
    if name in PRIMITIVE_COMPILERS:
        raise PrimitiveCompileError(
            f"Duplicate primitive compiler registration: '{name}'"
        )
    PRIMITIVE_COMPILERS[name] = handler


def list_primitive_compiler_names() -> list[str]:
    return sorted(PRIMITIVE_COMPILERS.keys())


def compile_primitive_to_cadquery_script(feature) -> list[str]:
    """Compile a single PrimitiveFeature into CadQuery Python code lines.

    Dispatches through PRIMITIVE_COMPILERS registry.
    """
    name = feature.primitive_name
    handler = PRIMITIVE_COMPILERS.get(name)
    if handler is None:
        available = list_primitive_compiler_names()
        raise PrimitiveCompileError(
            f"Unknown primitive '{name}'. "
            f"Available primitive compilers: {available if available else '(none)'}"
        )
    return handler(feature)


def _compile_involute_spur_gear(feature) -> list[str]:
    params = feature.parameters

    param_lines = []
    for k, v in params.items():
        if isinstance(v, str):
            param_lines.append(f'    "{k}": "{v}",')
        else:
            param_lines.append(f'    "{k}": {v},')

    code = f"""# [Primitive: involute_spur_gear]
from seekflow_engineering_tools.geometry_primitives.gears.cq_gears_adapter import (
    cq_gears_available,
    build_involute_spur_gear_cq_gears,
)
from seekflow_engineering_tools.geometry_primitives.gears.cadquery_fallback import (
    build_visual_spur_gear_fallback,
)
from seekflow_engineering_tools.geometry_primitives.gears.metadata import (
    write_primitive_metadata,
)
from seekflow_engineering_tools.geometry_primitives.gears.standards import (
    spur_gear_reference_dimensions,
)

_params = {{
{chr(10).join(param_lines)}
}}

if cq_gears_available():
    result, PRIMITIVE_METADATA["involute_spur_gear"] = build_involute_spur_gear_cq_gears(_params)
else:
    BUILD_WARNINGS.append("cq_gears is not available; using visual fallback (NOT certified involute).")
    result, PRIMITIVE_METADATA["involute_spur_gear"] = build_visual_spur_gear_fallback(_params)
    BUILD_WARNINGS.extend(
        PRIMITIVE_METADATA["involute_spur_gear"].get("warnings", [])
    )
"""
    return code.strip().split("\n")


# ── Register built-in primitive compilers ──
register_primitive_compiler("involute_spur_gear", _compile_involute_spur_gear)
