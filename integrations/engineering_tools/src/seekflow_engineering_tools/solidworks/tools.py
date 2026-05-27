"""SolidWorks 2025 SeekFlow tools."""

from __future__ import annotations

from seekflow import tool
from seekflow.types import ToolPolicy

from pathlib import Path as _Path

from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_extension, ensure_inside_workspace
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient


def _assert_file_created(path, label="output", min_size=1):
    """Raise if *path* does not exist or is empty."""
    p = _Path(path) if not isinstance(path, _Path) else path
    if not p.exists():
        raise FileNotFoundError(f"{label} file was not created: {p}")
    if p.stat().st_size < min_size:
        raise ValueError(f"{label} file is empty: {p} ({p.stat().st_size} bytes)")


def _require_positive(name, value):
    """Raise if *value* is not > 0."""
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")


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
            ensure_extension(out_sldprt_path, {".sldprt"})

            out_step_path = None
            if out_step:
                out_step_path = ensure_inside_workspace(config.workspace_root, out_step)
                ensure_extension(out_step_path, {".step", ".stp"})

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
            if not client.save_as(model, out_sldprt_path):
                raise RuntimeError(f"SolidWorks SaveAs failed for {out_sldprt_path}")
            _assert_file_created(out_sldprt_path, "SLDPRT")

            files_created = [str(out_sldprt_path)]

            # Export STEP if requested
            if out_step_path:
                if not client.export_step(model, out_step_path):
                    raise RuntimeError(f"SolidWorks STEP export failed for {out_step_path}")
                _assert_file_created(out_step_path, "STEP")
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

    # ── create_flanged_hub_part ─────────────────────────────────────

    @tool(
        name="solidworks_create_flanged_hub_part",
        description=(
            "Create a flanged hub in SolidWorks 2025 — flange disc, central "
            "hub boss, centre bore, and equally spaced bolt holes on a PCD. "
            "All dimensions in mm. Optionally export STEP."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def solidworks_create_flanged_hub_part(
        flange_dia_mm: float,
        flange_thickness_mm: float,
        hub_dia_mm: float,
        hub_height_mm: float,
        bore_dia_mm: float,
        bolt_pcd_mm: float,
        bolt_dia_mm: float,
        bolt_count: int,
        out_sldprt: str,
        out_step: str | None = None,
    ) -> dict:
        try:
            # Geometry constraints
            if flange_dia_mm <= hub_dia_mm:
                raise ValueError(f"flange_dia_mm ({flange_dia_mm}) must be > hub_dia_mm ({hub_dia_mm})")
            if hub_dia_mm <= bore_dia_mm:
                raise ValueError(f"hub_dia_mm ({hub_dia_mm}) must be > bore_dia_mm ({bore_dia_mm})")
            if bolt_count < 3:
                raise ValueError(f"bolt_count ({bolt_count}) must be >= 3")
            if bolt_pcd_mm >= flange_dia_mm:
                raise ValueError(f"bolt_pcd_mm ({bolt_pcd_mm}) must be < flange_dia_mm ({flange_dia_mm})")
            if bolt_pcd_mm <= hub_dia_mm:
                raise ValueError(f"bolt_pcd_mm ({bolt_pcd_mm}) must be > hub_dia_mm ({hub_dia_mm})")

            out_sldprt_path = ensure_inside_workspace(config.workspace_root, out_sldprt)
            ensure_extension(out_sldprt_path, {".sldprt"})
            out_step_path = None
            if out_step:
                out_step_path = ensure_inside_workspace(config.workspace_root, out_step)
                ensure_extension(out_step_path, {".step", ".stp"})

            if out_sldprt_path.exists() and not config.allow_overwrite:
                return EngineeringActionResult(
                    ok=False,
                    software="solidworks",
                    action="create_flanged_hub_part",
                    error=f"Output file {out_sldprt_path} already exists.",
                ).model_dump()

            client = SolidWorksClient(
                visible=config.solidworks_visible,
                part_template=config.solidworks_part_template,
            ).connect()

            model = client.new_part()
            client.create_flanged_hub(
                model,
                flange_dia_m=flange_dia_mm / 1000.0,
                flange_h_m=flange_thickness_mm / 1000.0,
                hub_dia_m=hub_dia_mm / 1000.0,
                hub_h_m=hub_height_mm / 1000.0,
                bore_dia_m=bore_dia_mm / 1000.0,
                bolt_pcd_m=bolt_pcd_mm / 1000.0,
                bolt_dia_m=bolt_dia_mm / 1000.0,
                bolt_count=bolt_count,
            )

            if not client.save_as(model, out_sldprt_path):
                raise RuntimeError(f"SolidWorks SaveAs failed for {out_sldprt_path}")
            _assert_file_created(out_sldprt_path, "SLDPRT")
            files_created = [str(out_sldprt_path)]

            if out_step_path:
                if not client.export_step(model, out_step_path):
                    raise RuntimeError(f"SolidWorks STEP export failed for {out_step_path}")
                _assert_file_created(out_step_path, "STEP")
                files_created.append(str(out_step_path))

            return EngineeringActionResult(
                ok=True,
                software="solidworks",
                action="create_flanged_hub_part",
                message="SolidWorks flanged hub created successfully.",
                files_created=files_created,
                metrics={
                    "flange_dia_mm": flange_dia_mm,
                    "flange_thickness_mm": flange_thickness_mm,
                    "hub_dia_mm": hub_dia_mm,
                    "hub_height_mm": hub_height_mm,
                    "bore_dia_mm": bore_dia_mm,
                    "bolt_pcd_mm": bolt_pcd_mm,
                    "bolt_dia_mm": bolt_dia_mm,
                    "bolt_count": bolt_count,
                    "expected_through_hole_count": bolt_count + 1,
                },
            ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="solidworks",
                action="create_flanged_hub_part",
                error=str(exc),
            ).model_dump()

    solidworks_create_flanged_hub_part = solidworks_create_flanged_hub_part.with_policy(
        _solidworks_write_policy(config, {"out_sldprt", "out_step"})
    )

    # ── create_spur_gear_part ───────────────────────────────────────

    @tool(
        name="solidworks_create_spur_gear_part",
        description=(
            "Create a spur gear in SolidWorks 2025 — star-polygon gear body "
            "with a centre bore. All dimensions in mm. "
            "Uses module (metric gear standard) and tooth count. "
            "Optionally export STEP."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def solidworks_create_spur_gear_part(
        module_mm: float,
        teeth: int,
        face_width_mm: float,
        bore_dia_mm: float,
        out_sldprt: str,
        out_step: str | None = None,
    ) -> dict:
        try:
            # Geometry constraints
            if module_mm <= 0:
                raise ValueError(f"module_mm ({module_mm}) must be > 0")
            if teeth < 6:
                raise ValueError(f"teeth ({teeth}) must be >= 6")
            if face_width_mm <= 0:
                raise ValueError(f"face_width_mm ({face_width_mm}) must be > 0")
            if bore_dia_mm <= 0:
                raise ValueError(f"bore_dia_mm ({bore_dia_mm}) must be > 0")

            out_sldprt_path = ensure_inside_workspace(config.workspace_root, out_sldprt)
            ensure_extension(out_sldprt_path, {".sldprt"})
            out_step_path = None
            if out_step:
                out_step_path = ensure_inside_workspace(config.workspace_root, out_step)
                ensure_extension(out_step_path, {".step", ".stp"})

            if out_sldprt_path.exists() and not config.allow_overwrite:
                return EngineeringActionResult(
                    ok=False,
                    software="solidworks",
                    action="create_spur_gear_part",
                    error=f"Output file {out_sldprt_path} already exists.",
                ).model_dump()

            client = SolidWorksClient(
                visible=config.solidworks_visible,
                part_template=config.solidworks_part_template,
            ).connect()

            model = client.new_part()
            client.create_spur_gear(
                model,
                module_m=module_mm / 1000.0,
                teeth=teeth,
                face_width_m=face_width_mm / 1000.0,
                bore_dia_m=bore_dia_mm / 1000.0,
            )

            if not client.save_as(model, out_sldprt_path):
                raise RuntimeError(f"SolidWorks SaveAs failed for {out_sldprt_path}")
            _assert_file_created(out_sldprt_path, "SLDPRT")
            files_created = [str(out_sldprt_path)]

            if out_step_path:
                if not client.export_step(model, out_step_path):
                    raise RuntimeError(f"SolidWorks STEP export failed for {out_step_path}")
                _assert_file_created(out_step_path, "STEP")
                files_created.append(str(out_step_path))

            return EngineeringActionResult(
                ok=True,
                software="solidworks",
                action="create_spur_gear_part",
                message="SolidWorks spur gear created successfully.",
                files_created=files_created,
                metrics={
                    "module_mm": module_mm,
                    "teeth": teeth,
                    "face_width_mm": face_width_mm,
                    "bore_dia_mm": bore_dia_mm,
                    "pitch_dia_mm": module_mm * teeth,
                },
            ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="solidworks",
                action="create_spur_gear_part",
                error=str(exc),
            ).model_dump()

    solidworks_create_spur_gear_part = solidworks_create_spur_gear_part.with_policy(
        _solidworks_write_policy(config, {"out_sldprt", "out_step"})
    )

    # ── create_true_involute_gear_part ──────────────────────────────

    @tool(
        name="solidworks_create_true_involute_gear_part",
        description=(
            "Create a standard involute spur gear in SolidWorks 2025 using "
            "mathematically correct tooth profile (ISO 53 / DIN 867). "
            "Uses the involute curve equation for true flank geometry. "
            "All dimensions in mm. Optionally export STEP."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def solidworks_create_true_involute_gear_part(
        module_mm: float,
        teeth: int,
        face_width_mm: float,
        bore_dia_mm: float,
        pressure_angle_deg: float = 20.0,
        out_sldprt: str = "",
        out_step: str | None = None,
    ) -> dict:
        try:
            out_sldprt_path = ensure_inside_workspace(config.workspace_root, out_sldprt)
            out_step_path = None
            if out_step:
                out_step_path = ensure_inside_workspace(config.workspace_root, out_step)

            if out_sldprt_path.exists() and not config.allow_overwrite:
                return EngineeringActionResult(
                    ok=False, software="solidworks",
                    action="create_true_involute_gear_part",
                    error=f"Output file {out_sldprt_path} already exists.",
                ).model_dump()

            client = SolidWorksClient(
                visible=config.solidworks_visible,
                part_template=config.solidworks_part_template,
            ).connect()

            model = client.new_part()
            client.create_spur_gear_true_involute(
                model,
                module_m=module_mm / 1000.0,
                teeth=teeth,
                face_width_m=face_width_mm / 1000.0,
                bore_dia_m=bore_dia_mm / 1000.0,
                pressure_angle_deg=pressure_angle_deg,
            )

            client.save_as(model, out_sldprt_path)
            files_created = [str(out_sldprt_path)]

            if out_step_path:
                client.export_step(model, out_step_path)
                files_created.append(str(out_step_path))

            return EngineeringActionResult(
                ok=True,
                software="solidworks",
                action="create_true_involute_gear_part",
                message="SolidWorks true involute gear created successfully.",
                files_created=files_created,
                metrics={
                    "module_mm": module_mm,
                    "teeth": teeth,
                    "face_width_mm": face_width_mm,
                    "bore_dia_mm": bore_dia_mm,
                    "pressure_angle_deg": pressure_angle_deg,
                    "pitch_dia_mm": module_mm * teeth,
                    "base_dia_mm": module_mm * teeth * 0.9396926,  # cos(20°)
                },
            ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="solidworks",
                action="create_true_involute_gear_part",
                error=str(exc),
            ).model_dump()

    solidworks_create_true_involute_gear_part = solidworks_create_true_involute_gear_part.with_policy(
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
        solidworks_create_flanged_hub_part,
        solidworks_create_spur_gear_part,
        solidworks_create_true_involute_gear_part,
        solidworks_export_step,
    ])
    return tools
