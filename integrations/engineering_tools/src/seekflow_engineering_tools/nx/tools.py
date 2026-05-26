"""NX 18.0 SeekFlow tools."""

from __future__ import annotations

from seekflow import tool
from seekflow.types import ToolPolicy

from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_inside_workspace
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.nx.job_queue import NXJobQueue


def build_nx_tools(config: EngineeringToolsConfig):
    tools: list = []
    job_root = config.nx_job_root or (config.workspace_root / "nx_jobs")

    # ── health_check ────────────────────────────────────────────────

    @tool(
        name="nx_health_check",
        description=(
            "Check whether the NX job queue directory exists. "
            "This does not guarantee that the NX bridge journal is running."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def nx_health_check() -> dict:
        try:
            q = NXJobQueue(job_root)
            status = q.queue_status()
            return EngineeringActionResult(
                ok=True,
                software="nx",
                action="health_check",
                message=(
                    "NX job queue is available. "
                    "Ensure nx_bridge_bootstrap.py is running inside NX 18.0."
                ),
                metrics={"job_root": str(job_root), **status},
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="nx",
                action="health_check",
                error=str(exc),
            ).model_dump()

    nx_health_check = nx_health_check.with_policy(
        ToolPolicy(
            capabilities={"cad.nx.read", "filesystem.read"},
            risk="read",
            timeout_s=30,
            workspace_root=config.workspace_root,
            parallel_safe=True,
        )
    )

    # ── create_block_part ───────────────────────────────────────────

    @tool(
        name="nx_create_block_part",
        description=(
            "Submit a job to NX 18.0 bridge to create a block part. "
            "Requires nx_bridge_bootstrap.py running inside NX."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def nx_create_block_part(
        length_mm: float,
        width_mm: float,
        height_mm: float,
        out_prt: str,
        out_step: str | None = None,
    ) -> dict:
        try:
            out_prt_path = ensure_inside_workspace(config.workspace_root, out_prt)

            # Overwrite check
            if out_prt_path.exists() and not config.allow_overwrite:
                return EngineeringActionResult(
                    ok=False,
                    software="nx",
                    action="create_block_part",
                    error=f"Output file {out_prt_path} already exists.",
                ).model_dump()

            params: dict = {
                "length_mm": length_mm,
                "width_mm": width_mm,
                "height_mm": height_mm,
                "out_prt": str(out_prt_path),
            }

            if out_step:
                out_step_path = ensure_inside_workspace(config.workspace_root, out_step)
                params["out_step"] = str(out_step_path)

            q = NXJobQueue(job_root)
            job_id = q.submit("create_block_part", params)
            result = q.wait(job_id, timeout_s=config.nx_default_timeout_s)

            return EngineeringActionResult(
                ok=bool(result.get("ok")),
                software="nx",
                action="create_block_part",
                message=result.get("message", ""),
                files_created=result.get("files_created", []),
                metrics=result.get("metrics", {}),
                error=result.get("error"),
            ).model_dump()

        except TimeoutError as exc:
            return EngineeringActionResult(
                ok=False,
                software="nx",
                action="create_block_part",
                error=str(exc),
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="nx",
                action="create_block_part",
                error=str(exc),
            ).model_dump()

    nx_create_block_part = nx_create_block_part.with_policy(
        ToolPolicy(
            capabilities={"cad.nx.write", "filesystem.write"},
            risk="write",
            timeout_s=config.nx_default_timeout_s + 10,
            workspace_root=config.workspace_root,
            path_params=frozenset({"out_prt", "out_step"}),
            parallel_safe=False,
            requires_approval=False,
            idempotent=False,
        )
    )

    # ── export_step ─────────────────────────────────────────────────

    @tool(
        name="nx_export_step",
        description=(
            "Submit a job to NX 18.0 bridge to export an existing .prt as STEP."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def nx_export_step(
        input_prt: str,
        out_step: str,
    ) -> dict:
        try:
            in_path = ensure_inside_workspace(config.workspace_root, input_prt)
            out_path = ensure_inside_workspace(config.workspace_root, out_step)

            if not in_path.exists():
                raise FileNotFoundError(f"Input file not found: {in_path}")

            if out_path.exists() and not config.allow_overwrite:
                return EngineeringActionResult(
                    ok=False,
                    software="nx",
                    action="export_step",
                    error=f"Output file {out_path} already exists.",
                ).model_dump()

            q = NXJobQueue(job_root)
            job_id = q.submit("export_step", {
                "input_prt": str(in_path),
                "out_step": str(out_path),
            })
            result = q.wait(job_id, timeout_s=config.nx_default_timeout_s)

            return EngineeringActionResult(
                ok=bool(result.get("ok")),
                software="nx",
                action="export_step",
                message=result.get("message", ""),
                files_created=result.get("files_created", []),
                error=result.get("error"),
            ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="nx",
                action="export_step",
                error=str(exc),
            ).model_dump()

    nx_export_step = nx_export_step.with_policy(
        ToolPolicy(
            capabilities={"cad.nx.write", "filesystem.write"},
            risk="write",
            timeout_s=config.nx_default_timeout_s + 10,
            workspace_root=config.workspace_root,
            path_params=frozenset({"input_prt", "out_step"}),
            parallel_safe=False,
            requires_approval=False,
            idempotent=False,
        )
    )

    tools.extend([
        nx_health_check,
        nx_create_block_part,
        nx_export_step,
    ])
    return tools
