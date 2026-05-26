"""SolidWorks 2025 SeekFlow tools."""

from __future__ import annotations

from seekflow import tool
from seekflow.types import ToolPolicy

from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_inside_workspace
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient


def _solidworks_write_policy(
    config: EngineeringToolsConfig, path_params: set[str]
) -> ToolPolicy:
    return ToolPolicy(
        capabilities={"cad.solidworks.write", "filesystem.write"},
        risk="write",
        timeout_s=config.solidworks_default_timeout_s,
        workspace_root=config.workspace_root,
        path_params=frozenset(path_params),
        parallel_safe=False,
        requires_approval=False,
        idempotent=False,
    )


def build_solidworks_tools(config: EngineeringToolsConfig):
    tools: list = []

    # ── health_check ────────────────────────────────────────────────

    @tool(
        name="solidworks_health_check",
        description="Check whether local SolidWorks 2025 COM automation is available.",
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def solidworks_health_check() -> dict:
        try:
            client = SolidWorksClient(
                visible=config.solidworks_visible,
                part_template=config.solidworks_part_template,
            )
            info = client.health_check()
            return EngineeringActionResult(
                ok=True,
                software="solidworks",
                action="health_check",
                message="SolidWorks COM is available.",
                metrics=info,
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="solidworks",
                action="health_check",
                error=str(exc),
            ).model_dump()

    solidworks_health_check = solidworks_health_check.with_policy(
        ToolPolicy(
            capabilities={"cad.solidworks.read"},
            risk="read",
            timeout_s=60,
            parallel_safe=False,
        )
    )

    # ── create_box_part ─────────────────────────────────────────────

    @tool(
        name="solidworks_create_box_part",
        description=(
            "Create a rectangular block part in SolidWorks 2025 and optionally "
            "export STEP. All dimensions are in millimeters."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def solidworks_create_box_part(
        length_mm: float,
        width_mm: float,
        height_mm: float,
        out_sldprt: str,
        out_step: str | None = None,
    ) -> dict:
        try:
            out_sldprt_path = ensure_inside_workspace(config.workspace_root, out_sldprt)

            out_step_path = None
            if out_step:
                out_step_path = ensure_inside_workspace(config.workspace_root, out_step)

            # Overwrite check
            if out_sldprt_path.exists() and not config.allow_overwrite:
                return EngineeringActionResult(
                    ok=False,
                    software="solidworks",
                    action="create_box_part",
                    error=f"Output file {out_sldprt_path} already exists.",
                ).model_dump()

            client = SolidWorksClient(
                visible=config.solidworks_visible,
                part_template=config.solidworks_part_template,
            ).connect()

            # Convert mm → m for SolidWorks COM API
            length_m = length_mm / 1000.0
            width_m = width_mm / 1000.0
            height_m = height_mm / 1000.0

            model = client.new_part()
            client.create_extruded_box(model, length_m, width_m, height_m)

            # Save SLDPRT
            client.save_as(model, out_sldprt_path)

            files_created = [str(out_sldprt_path)]

            # Export STEP if requested
            if out_step_path:
                client.export_step(model, out_step_path)
                files_created.append(str(out_step_path))

            return EngineeringActionResult(
                ok=True,
                software="solidworks",
                action="create_box_part",
                message="SolidWorks part created successfully.",
                files_created=files_created,
            ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="solidworks",
                action="create_box_part",
                error=str(exc),
            ).model_dump()

    solidworks_create_box_part = solidworks_create_box_part.with_policy(
        _solidworks_write_policy(config, {"out_sldprt", "out_step"})
    )

    # ── export_step ─────────────────────────────────────────────────

    @tool(
        name="solidworks_export_step",
        description="Open an existing SLDPRT and export it as STEP.",
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def solidworks_export_step(
        input_sldprt: str,
        out_step: str,
    ) -> dict:
        try:
            in_path = ensure_inside_workspace(config.workspace_root, input_sldprt)
            out_path = ensure_inside_workspace(config.workspace_root, out_step)

            if not in_path.exists():
                raise FileNotFoundError(f"Input file not found: {in_path}")

            if out_path.exists() and not config.allow_overwrite:
                return EngineeringActionResult(
                    ok=False,
                    software="solidworks",
                    action="export_step",
                    error=f"Output file {out_path} already exists.",
                ).model_dump()

            client = SolidWorksClient(
                visible=config.solidworks_visible,
            ).connect()

            model = client.open_document(in_path)
            client.export_step(model, out_path)

            return EngineeringActionResult(
                ok=True,
                software="solidworks",
                action="export_step",
                message=f"STEP exported to {out_path}",
                files_created=[str(out_path)],
            ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="solidworks",
                action="export_step",
                error=str(exc),
            ).model_dump()

    solidworks_export_step = solidworks_export_step.with_policy(
        _solidworks_write_policy(config, {"input_sldprt", "out_step"})
    )

    tools.extend([
        solidworks_health_check,
        solidworks_create_box_part,
        solidworks_export_step,
    ])
    return tools
