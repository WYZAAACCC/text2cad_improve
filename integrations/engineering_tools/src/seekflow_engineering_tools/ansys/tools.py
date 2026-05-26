"""ANSYS 18.1 SeekFlow tools."""

from __future__ import annotations

import time

from seekflow import tool
from seekflow.types import ToolPolicy

from seekflow_engineering_tools.ansys.apdl_runner import AnsysAPDLRunner
from seekflow_engineering_tools.ansys.apdl_templates import (
    static_cantilever_beam_rect_apdl,
)
from seekflow_engineering_tools.ansys.parsers import parse_result_summary
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_inside_workspace
from seekflow_engineering_tools.common.validation import sanitise_jobname
from seekflow_engineering_tools.config import EngineeringToolsConfig


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

            # Parse results
            summary_path = job_dir / "result_summary.txt"
            metrics = {}
            if summary_path.exists():
                metrics = parse_result_summary(summary_path)

            files_created = [
                str(inp_path),
                run["output_file"],
            ]
            if summary_path.exists():
                files_created.append(str(summary_path))

            warnings: list[str] = []
            if run["has_warning"]:
                warnings.append("ANSYS output contains WARNING messages.")

            return EngineeringActionResult(
                ok=not run["has_error"],
                software="ansys",
                action="static_cantilever_beam_rect",
                message="ANSYS APDL batch job finished.",
                files_created=files_created,
                log_path=run["output_file"],
                stdout_tail=run["stdout_tail"],
                stderr_tail=run["stderr_tail"],
                metrics=metrics,
                warnings=warnings,
                error=None if not run["has_error"] else "ANSYS reported an error.",
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
            "Available templates: static_cantilever_beam_rect."
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

            safe_jobname = sanitise_jobname(jobname)
            job_dir = ensure_inside_workspace(
                config.workspace_root, f"ansys_jobs/{safe_jobname}"
            )
            job_dir.mkdir(parents=True, exist_ok=True)

            inp_path = job_dir / f"{safe_jobname}.inp"
            apdl = render_template(template_name, **parameters)
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

            summary_path = job_dir / "result_summary.txt"
            metrics = parse_result_summary(summary_path)

            return EngineeringActionResult(
                ok=not run["has_error"],
                software="ansys",
                action="run_apdl_template",
                message="ANSYS APDL template job finished.",
                files_created=[str(inp_path), run["output_file"]],
                log_path=run["output_file"],
                metrics=metrics,
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
        ansys_static_cantilever_beam_rect,
        ansys_run_apdl_template,
    ])
    return tools
