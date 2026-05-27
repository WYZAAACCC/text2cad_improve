"""ANSYS 18.1 SeekFlow tools."""

from __future__ import annotations

import time

from seekflow import tool
from seekflow.types import ToolPolicy

from seekflow_engineering_tools.ansys.apdl_runner import AnsysAPDLRunner
from seekflow_engineering_tools.ansys.apdl_templates import (
    static_cantilever_beam_rect_apdl,
    list_templates,
)
from seekflow_engineering_tools.ansys.parsers import parse_result_summary
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_inside_workspace
from seekflow_engineering_tools.common.validation import sanitise_jobname
from seekflow_engineering_tools.config import EngineeringToolsConfig

# Preloaded template schemas for ansys_list_apdl_templates
_ANSYS_TEMPLATE_SCHEMAS = {
    "static_cantilever_beam_rect": {
        "analysis_type": "static_structural",
        "units": "mm,N,MPa",
        "parameters": {
            "length_mm": {"type": "float", "required": True, "min": 1},
            "width_mm": {"type": "float", "required": True, "min": 0.1},
            "height_mm": {"type": "float", "required": True, "min": 0.1},
            "force_n": {"type": "float", "required": True},
            "element_size_mm": {"type": "float", "required": False, "default": 10.0},
        },
        "metrics": ["max_displacement_mm", "max_von_mises_mpa"],
    },
    "plate_with_hole_tension": {
        "analysis_type": "static_structural",
        "units": "mm,N,MPa",
        "parameters": {
            "plate_width_mm": {"type": "float", "default": 200.0},
            "plate_height_mm": {"type": "float", "default": 100.0},
            "plate_thickness_mm": {"type": "float", "default": 10.0},
            "hole_diameter_mm": {"type": "float", "default": 20.0},
            "tensile_stress_mpa": {"type": "float", "default": 100.0},
            "element_size_mm": {"type": "float", "default": 5.0},
        },
        "metrics": ["max_von_mises_mpa", "stress_concentration_factor"],
    },
    "beam_thermal": {
        "analysis_type": "thermal_steady",
        "units": "mm,C,W",
        "parameters": {
            "length_mm": {"type": "float", "default": 200.0},
            "width_mm": {"type": "float", "default": 20.0},
            "height_mm": {"type": "float", "default": 20.0},
            "temp_left_c": {"type": "float", "default": 100.0},
            "temp_right_c": {"type": "float", "default": 0.0},
            "ambient_temp_c": {"type": "float", "default": 25.0},
            "element_size_mm": {"type": "float", "default": 5.0},
        },
        "metrics": ["tmin_c", "tmax_c", "tmid_c"],
    },
    "cantilever_modal": {
        "analysis_type": "modal",
        "units": "mm,tonne,N,MPa",
        "parameters": {
            "length_mm": {"type": "float", "default": 200.0},
            "width_mm": {"type": "float", "default": 20.0},
            "height_mm": {"type": "float", "default": 20.0},
            "young_mpa": {"type": "float", "default": 210000.0},
            "density_kgmm3": {"type": "float", "default": 7.85e-6},
            "poisson": {"type": "float", "default": 0.3},
            "n_modes": {"type": "int", "default": 5},
            "element_size_mm": {"type": "float", "default": 10.0},
        },
        "metrics": ["modal_frequencies_hz"],
    },
    "buckling_column": {
        "analysis_type": "buckling",
        "units": "mm,N,MPa",
        "parameters": {
            "length_mm": {"type": "float", "default": 500.0},
            "width_mm": {"type": "float", "default": 20.0},
            "height_mm": {"type": "float", "default": 20.0},
            "young_mpa": {"type": "float", "default": 210000.0},
            "poisson": {"type": "float", "default": 0.3},
            "element_size_mm": {"type": "float", "default": 10.0},
        },
        "metrics": ["buckling_load_factor", "pcr_n"],
    },
    "bilinear_plastic": {
        "analysis_type": "bilinear_plastic",
        "units": "mm,N,MPa",
        "parameters": {
            "length_mm": {"type": "float", "default": 100.0},
            "width_mm": {"type": "float", "default": 10.0},
            "height_mm": {"type": "float", "default": 10.0},
            "young_mpa": {"type": "float", "default": 210000.0},
            "yield_stress_mpa": {"type": "float", "default": 235.0},
            "tangent_modulus_mpa": {"type": "float", "default": 2100.0},
            "displacement_mm": {"type": "float", "default": 5.0},
            "element_size_mm": {"type": "float", "default": 5.0},
            "n_substeps": {"type": "int", "default": 20},
        },
        "metrics": ["max_plastic_strain", "tip_displacement_mm"],
    },
}


def build_ansys_tools(config: EngineeringToolsConfig):
    tools: list = []

    # ── health_check ────────────────────────────────────────────────

    @tool(
        name="ansys_health_check",
        description="Check whether ANSYS 18.1 Mechanical APDL executable is configured.",
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def ansys_health_check() -> dict:
        try:
            if config.ansys181_exe is None:
                raise ValueError("ansys181_exe is not configured. Set ANSYS181_EXE env var.")

            runner = AnsysAPDLRunner(
                ansys_exe=config.ansys181_exe,
                workspace_root=config.workspace_root,
                default_timeout_s=config.ansys_default_timeout_s,
                default_nproc=config.ansys_default_nproc,
            )
            info = runner.health_check()
            return EngineeringActionResult(
                ok=bool(info["exists"]),
                software="ansys",
                action="health_check",
                message=(
                    "ANSYS executable found."
                    if info["exists"]
                    else f"ANSYS executable NOT found at {config.ansys181_exe}"
                ),
                metrics=info,
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="ansys",
                action="health_check",
                error=str(exc),
            ).model_dump()

    ansys_health_check = ansys_health_check.with_policy(
        ToolPolicy(
            capabilities={"cae.ansys.read"},
            risk="read",
            timeout_s=30,
            parallel_safe=True,
        )
    )

    # ── list_apdl_templates ──────────────────────────────────────────

    @tool(
        name="ansys_list_apdl_templates",
        description=(
            "List all built-in ANSYS 18.1 Mechanical APDL templates and "
            "their expected parameters, units, analysis types, and result metrics."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def ansys_list_apdl_templates() -> dict:
        try:
            return EngineeringActionResult(
                ok=True,
                software="ansys",
                action="list_apdl_templates",
                message=f"Found {len(_ANSYS_TEMPLATE_SCHEMAS)} ANSYS APDL templates.",
                metrics={"templates": _ANSYS_TEMPLATE_SCHEMAS},
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="ansys",
                action="list_apdl_templates",
                error=str(exc),
            ).model_dump()

    ansys_list_apdl_templates = ansys_list_apdl_templates.with_policy(
        ToolPolicy(
            capabilities={"cae.ansys.read"},
            risk="read",
            timeout_s=10,
            parallel_safe=True,
        )
    )

    # ── static_cantilever_beam_rect ─────────────────────────────────

    @tool(
        name="ansys_static_cantilever_beam_rect",
        description=(
            "Run a simple ANSYS 18.1 APDL static analysis for a rectangular "
            "cantilever beam. Units: mm, N, MPa."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def ansys_static_cantilever_beam_rect(
        length_mm: float,
        width_mm: float,
        height_mm: float,
        force_n: float,
        jobname: str,
        element_size_mm: float = 10.0,
    ) -> dict:
        try:
            if config.ansys181_exe is None:
                raise ValueError("ansys181_exe is not configured.")

            safe_jobname = sanitise_jobname(jobname)
            if not safe_jobname:
                safe_jobname = f"ansys_job_{int(time.time())}"

            job_dir = ensure_inside_workspace(
                config.workspace_root, f"ansys_jobs/{safe_jobname}"
            )
            job_dir.mkdir(parents=True, exist_ok=True)

            # Check overwrite safety
            out_file = job_dir / f"{safe_jobname}.out"
            if out_file.exists() and not config.allow_overwrite:
                return EngineeringActionResult(
                    ok=False,
                    software="ansys",
                    action="static_cantilever_beam_rect",
                    error=(
                        f"Output file {out_file} already exists and "
                        "allow_overwrite is disabled."
                    ),
                ).model_dump()

            # Generate APDL input
            inp_path = job_dir / f"{safe_jobname}.inp"
            apdl = static_cantilever_beam_rect_apdl(
                length_mm=length_mm,
                width_mm=width_mm,
                height_mm=height_mm,
                force_n=force_n,
                element_size_mm=element_size_mm,
            )
            inp_path.write_text(apdl, encoding="utf-8")

            # Run
            runner = AnsysAPDLRunner(
                ansys_exe=config.ansys181_exe,
                workspace_root=config.workspace_root,
                default_timeout_s=config.ansys_default_timeout_s,
                default_nproc=config.ansys_default_nproc,
            )
            run = runner.run_apdl_file(
                input_file=inp_path,
                job_dir=job_dir,
                jobname=safe_jobname,
                timeout_s=config.ansys_default_timeout_s,
            )

            # APDL process nonzero exit → fail
            if run["has_error"]:
                return EngineeringActionResult(
                    ok=False,
                    software="ansys",
                    action="static_cantilever_beam_rect",
                    message="ANSYS APDL run reported an error.",
                    files_created=[str(inp_path), run["output_file"]],
                    log_path=run["output_file"],
                    stdout_tail=run.get("stdout_tail"),
                    stderr_tail=run.get("stderr_tail"),
                    error="ANSYS APDL process reported an error.",
                ).model_dump()

            # Parse results — summary missing is error
            summary_path = job_dir / "result_summary.txt"
            if not summary_path.exists():
                return EngineeringActionResult(
                    ok=False,
                    software="ansys",
                    action="static_cantilever_beam_rect",
                    message="ANSYS APDL batch job finished but result_summary.txt was not generated.",
                    files_created=[str(inp_path), run["output_file"]],
                    log_path=run["output_file"],
                    error="ANSYS result_summary.txt missing — required for static_cantilever_beam_rect.",
                ).model_dump()

            metrics = parse_result_summary(summary_path)

            # Check required metrics are present
            required_metrics = [
                "max_displacement_mm", "max_von_mises_mpa",
            ]
            missing_metrics = [m for m in required_metrics if m not in metrics]
            if missing_metrics:
                return EngineeringActionResult(
                    ok=False,
                    software="ansys",
                    action="static_cantilever_beam_rect",
                    message="ANSYS APDL batch job finished but required metrics missing.",
                    files_created=[str(inp_path), run["output_file"], str(summary_path)],
                    log_path=run["output_file"],
                    metrics=metrics,
                    error=f"Required metrics missing: {', '.join(missing_metrics)}",
                ).model_dump()

            files_created = [str(inp_path), run["output_file"], str(summary_path)]
            warnings: list[str] = []
            if run.get("has_warning"):
                warnings.append("ANSYS output contains WARNING messages.")

            return EngineeringActionResult(
                ok=True,
                software="ansys",
                action="static_cantilever_beam_rect",
                message="ANSYS APDL batch job finished.",
                files_created=files_created,
                log_path=run["output_file"],
                stdout_tail=run.get("stdout_tail"),
                metrics=metrics,
                warnings=warnings,
            ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="ansys",
                action="static_cantilever_beam_rect",
                error=str(exc),
            ).model_dump()

    ansys_static_cantilever_beam_rect = ansys_static_cantilever_beam_rect.with_policy(
        ToolPolicy(
            capabilities={"cae.ansys.write", "cae.ansys.solve", "filesystem.write"},
            risk="write",
            timeout_s=config.ansys_default_timeout_s + 30,
            workspace_root=config.workspace_root,
            parallel_safe=False,
            requires_approval=False,
            idempotent=False,
        )
    )

    # ── run_apdl_template ───────────────────────────────────────────

    @tool(
        name="ansys_run_apdl_template",
        description=(
            "Run a named APDL template from the built-in library. "
            "Available templates: static_cantilever_beam_rect, "
            "plate_with_hole_tension, beam_thermal, cantilever_modal, "
            "buckling_column, bilinear_plastic. Units depend on template schema."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def ansys_run_apdl_template(
        template_name: str,
        parameters: dict,
        jobname: str,
    ) -> dict:
        try:
            if config.ansys181_exe is None:
                raise ValueError("ansys181_exe is not configured.")

            from seekflow_engineering_tools.ansys.apdl_templates import (
                render_template,
            )
            from seekflow_engineering_tools.ansys.template_registry import (
                validate_template_parameters,
            )

            # Validate parameters — unknown/missing/type error → fail
            try:
                validated_params = validate_template_parameters(template_name, parameters)
            except (ValueError, KeyError, TypeError) as exc:
                return EngineeringActionResult(
                    ok=False,
                    software="ansys",
                    action="run_apdl_template",
                    error=f"Template parameter validation failed: {exc}",
                ).model_dump()

            safe_jobname = sanitise_jobname(jobname)
            job_dir = ensure_inside_workspace(
                config.workspace_root, f"ansys_jobs/{safe_jobname}"
            )
            job_dir.mkdir(parents=True, exist_ok=True)

            inp_path = job_dir / f"{safe_jobname}.inp"
            apdl = render_template(template_name, **validated_params)
            inp_path.write_text(apdl, encoding="utf-8")

            runner = AnsysAPDLRunner(
                ansys_exe=config.ansys181_exe,
                workspace_root=config.workspace_root,
                default_timeout_s=config.ansys_default_timeout_s,
                default_nproc=config.ansys_default_nproc,
            )
            run = runner.run_apdl_file(
                input_file=inp_path,
                job_dir=job_dir,
                jobname=safe_jobname,
                timeout_s=config.ansys_default_timeout_s,
            )

            # APDL process nonzero exit → fail
            if run["has_error"]:
                return EngineeringActionResult(
                    ok=False,
                    software="ansys",
                    action="run_apdl_template",
                    message="ANSYS APDL run reported an error.",
                    files_created=[str(inp_path), run["output_file"]],
                    log_path=run["output_file"],
                    stdout_tail=run.get("stdout_tail"),
                    stderr_tail=run.get("stderr_tail"),
                    error="ANSYS APDL process reported an error.",
                ).model_dump()

            # Check template schema for required metrics
            schema = _ANSYS_TEMPLATE_SCHEMAS.get(template_name)
            required_metrics = schema.get("metrics", []) if schema else []

            # For templates with expected metrics, summary is mandatory
            summary_path = job_dir / "result_summary.txt"
            if required_metrics and not summary_path.exists():
                return EngineeringActionResult(
                    ok=False,
                    software="ansys",
                    action="run_apdl_template",
                    message=(
                        f"ANSYS APDL batch job finished but result_summary.txt "
                        f"was not generated for template '{template_name}'."
                    ),
                    files_created=[str(inp_path), run["output_file"]],
                    log_path=run["output_file"],
                    error=f"ANSYS result_summary.txt missing — required for template '{template_name}'.",
                ).model_dump()

            metrics = {}
            if summary_path.exists():
                metrics = parse_result_summary(summary_path)

            # Check required metrics are present
            if required_metrics:
                missing_metrics = [m for m in required_metrics if m not in metrics]
                if missing_metrics:
                    return EngineeringActionResult(
                        ok=False,
                        software="ansys",
                        action="run_apdl_template",
                        message="ANSYS APDL batch job finished but required metrics missing.",
                        files_created=[str(inp_path), run["output_file"]],
                        log_path=run["output_file"],
                        metrics=metrics,
                        error=f"Required metrics missing for '{template_name}': {', '.join(missing_metrics)}",
                    ).model_dump()

            files_created = [str(inp_path), run["output_file"]]
            if summary_path.exists():
                files_created.append(str(summary_path))
            warnings: list[str] = []
            if run.get("has_warning"):
                warnings.append("ANSYS output contains WARNING messages.")

            return EngineeringActionResult(
                ok=True,
                software="ansys",
                action="run_apdl_template",
                message="ANSYS APDL template job finished.",
                files_created=files_created,
                log_path=run["output_file"],
                stdout_tail=run.get("stdout_tail"),
                metrics=metrics,
                warnings=warnings,
            ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="ansys",
                action="run_apdl_template",
                error=str(exc),
            ).model_dump()

    ansys_run_apdl_template = ansys_run_apdl_template.with_policy(
        ToolPolicy(
            capabilities={"cae.ansys.write", "cae.ansys.solve", "filesystem.write"},
            risk="write",
            timeout_s=config.ansys_default_timeout_s + 30,
            workspace_root=config.workspace_root,
            parallel_safe=False,
            requires_approval=False,
            idempotent=False,
        )
    )

    tools.extend([
        ansys_health_check,
        ansys_list_apdl_templates,
        ansys_static_cantilever_beam_rect,
        ansys_run_apdl_template,
    ])
    return tools
