"""SeekFlow tools for the CadQuery backend.

Provides compile and inspect tools that don't require commercial CAD.
"""

from __future__ import annotations

from pathlib import Path

from seekflow import tool
from seekflow.types import ToolPolicy

from seekflow_engineering_tools.cadquery_backend.compiler import (
    compile_cad_ir_to_cadquery_script,
)
from seekflow_engineering_tools.cadquery_backend.inspector import (
    inspect_step_with_cadquery,
)
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.ir.cad import CADPartSpec


def build_cadquery_tools(config):
    """Build CadQuery tools that don't depend on commercial CAD availability."""
    tools: list = []

    @tool(
        name="cadquery_compile_cad_ir_to_script",
        description=(
            "Compile a CAD-IR spec into a CadQuery Python script. "
            "Useful for previewing generated geometry logic before running."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def cadquery_compile_cad_ir_to_script(spec: dict) -> dict:
        try:
            cad_spec = CADPartSpec.model_validate(spec)
            script = compile_cad_ir_to_cadquery_script(cad_spec)
            return EngineeringActionResult(
                ok=True,
                software="cadquery",
                action="compile_cad_ir_to_script",
                message=f"CadQuery script compiled ({len(script)} chars).",
                metrics={
                    "script_length": len(script),
                    "feature_count": len(cad_spec.features),
                },
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="compile_cad_ir_to_script",
                error=str(exc),
            ).model_dump()

    cadquery_compile_cad_ir_to_script = cadquery_compile_cad_ir_to_script.with_policy(
        ToolPolicy(
            capabilities={"cad.solidworks.read"},
            risk="read",
            timeout_s=30,
            parallel_safe=True,
        )
    )

    @tool(
        name="cadquery_inspect_step",
        description=(
            "Inspect a STEP file using CadQuery to extract bbox, volume, "
            "and solid count for model validation."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def cadquery_inspect_step(step_path: str) -> dict:
        try:
            info = inspect_step_with_cadquery(Path(step_path))
            if info.get("error"):
                return EngineeringActionResult(
                    ok=False,
                    software="cadquery",
                    action="inspect_step",
                    error=info["error"],
                    metrics=info,
                ).model_dump()

            return EngineeringActionResult(
                ok=True,
                software="cadquery",
                action="inspect_step",
                message="STEP inspection completed.",
                metrics=info,
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="inspect_step",
                error=str(exc),
            ).model_dump()

    cadquery_inspect_step = cadquery_inspect_step.with_policy(
        ToolPolicy(
            capabilities={"cad.solidworks.read"},
            risk="read",
            timeout_s=60,
            parallel_safe=True,
        )
    )

    tools.extend([
        cadquery_compile_cad_ir_to_script,
        cadquery_inspect_step,
    ])
    return tools
