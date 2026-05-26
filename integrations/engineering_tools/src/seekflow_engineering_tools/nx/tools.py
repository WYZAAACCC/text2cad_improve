"""NX 12.0 SeekFlow tools."""

from __future__ import annotations

import json
import time
from pathlib import Path

from seekflow import tool
from seekflow.types import ToolPolicy

from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_inside_workspace
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.nx.job_queue import NXJobQueue


# ── Heartbeat helpers ────────────────────────────────────────────────────────


def _heartbeat_path(job_root: Path) -> Path:
    return job_root / "running" / "heartbeat.json"


def _bridge_status(job_root: Path, stale_after_s: float = 15.0) -> dict:
    hp = _heartbeat_path(job_root)
    if not hp.exists():
        return {"bridge_running": False, "reason": "heartbeat_missing"}
    data = json.loads(hp.read_text(encoding="utf-8"))
    age_s = time.time() - float(data.get("time_epoch", 0))
    return {
        "bridge_running": age_s <= stale_after_s,
        "heartbeat_age_s": age_s,
        "heartbeat": data,
    }


# ── Job submission helper ────────────────────────────────────────────────────


def _submit_job_and_wait(
    config: EngineeringToolsConfig,
    job_root: Path,
    action: str,
    params: dict,
    out_prt: str,
    out_step: str | None = None,
) -> dict:
    """Submit a job to NX bridge, wait for completion, return EngineeringActionResult dict."""
    out_prt_path = ensure_inside_workspace(config.workspace_root, out_prt)

    if out_prt_path.exists() and not config.allow_overwrite:
        return EngineeringActionResult(
            ok=False,
            software="nx",
            action=action,
            error=f"Output file {out_prt_path} already exists.",
        ).model_dump()

    full_params: dict = {"out_prt": str(out_prt_path), **params}

    if out_step:
        out_step_path = ensure_inside_workspace(config.workspace_root, out_step)
        full_params["out_step"] = str(out_step_path)

    q = NXJobQueue(job_root)
    job_id = q.submit(action, full_params)
    result = q.wait(job_id, timeout_s=config.nx_default_timeout_s)

    return EngineeringActionResult(
        ok=bool(result.get("ok")),
        software="nx",
        action=action,
        message=result.get("message", ""),
        files_created=result.get("files_created", []),
        metrics=result.get("metrics", {}),
        error=result.get("error"),
    ).model_dump()


def build_nx_tools(config: EngineeringToolsConfig):
    tools: list = []
    job_root = config.nx_job_root or (config.workspace_root / "nx_jobs")

    # ── health_check ────────────────────────────────────────────────

    @tool(
        name="nx_health_check",
        description=(
            "Check the NX 12.0 bridge job queue and whether the bridge "
            "journal is alive (via heartbeat). "
            "Returns queue status and bridge running state."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def nx_health_check() -> dict:
        try:
            q = NXJobQueue(job_root)
            status = q.queue_status()
            bridge_info = _bridge_status(job_root)
            return EngineeringActionResult(
                ok=True,
                software="nx",
                action="health_check",
                message=(
                    "NX bridge is alive and processing jobs."
                    if bridge_info.get("bridge_running")
                    else (
                        "NX job queue directory exists, but bridge journal "
                        "may not be running. Start nx_bridge_bootstrap.py inside NX 12.0."
                    )
                ),
                metrics={
                    "job_root": str(job_root),
                    "bridge_running": bridge_info.get("bridge_running"),
                    "heartbeat_age_s": bridge_info.get("heartbeat_age_s"),
                    **status,
                },
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
            "Submit a job to NX 12.0 bridge to create a block part. "
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
            return _submit_job_and_wait(
                config=config,
                job_root=job_root,
                action="create_block_part",
                params={
                    "length_mm": length_mm,
                    "width_mm": width_mm,
                    "height_mm": height_mm,
                },
                out_prt=out_prt,
                out_step=out_step,
            )
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

    # ── create_block_with_hole ──────────────────────────────────────

    @tool(
        name="nx_create_block_with_hole",
        description=(
            "Submit a job to NX 12.0 bridge to create a block with a "
            "through-hole (via boolean subtract). "
            "Hole position defaults to centre of XY face."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def nx_create_block_with_hole(
        length_mm: float,
        width_mm: float,
        height_mm: float,
        hole_dia_mm: float,
        hole_x_mm: float | None = None,
        hole_z_mm: float | None = None,
        out_prt: str = "",
        out_step: str | None = None,
    ) -> dict:
        try:
            params: dict = {
                "length_mm": length_mm,
                "width_mm": width_mm,
                "height_mm": height_mm,
                "hole_dia_mm": hole_dia_mm,
            }
            if hole_x_mm is not None:
                params["hole_x"] = hole_x_mm
            if hole_z_mm is not None:
                params["hole_z"] = hole_z_mm

            return _submit_job_and_wait(
                config=config,
                job_root=job_root,
                action="create_block_with_hole",
                params=params,
                out_prt=out_prt,
                out_step=out_step,
            )
        except TimeoutError as exc:
            return EngineeringActionResult(
                ok=False,
                software="nx",
                action="create_block_with_hole",
                error=str(exc),
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="nx",
                action="create_block_with_hole",
                error=str(exc),
            ).model_dump()

    nx_create_block_with_hole = nx_create_block_with_hole.with_policy(
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

    # ── create_l_bracket ────────────────────────────────────────────

    @tool(
        name="nx_create_l_bracket",
        description=(
            "Submit a job to NX 12.0 bridge to create an L-bracket — "
            "two perpendicular blocks united via boolean."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def nx_create_l_bracket(
        base_length_mm: float,
        base_width_mm: float,
        thickness_mm: float,
        leg_height_mm: float,
        out_prt: str,
        out_step: str | None = None,
    ) -> dict:
        try:
            return _submit_job_and_wait(
                config=config,
                job_root=job_root,
                action="create_l_bracket",
                params={
                    "base_length": base_length_mm,
                    "base_width": base_width_mm,
                    "thickness": thickness_mm,
                    "leg_height": leg_height_mm,
                },
                out_prt=out_prt,
                out_step=out_step,
            )
        except TimeoutError as exc:
            return EngineeringActionResult(
                ok=False,
                software="nx",
                action="create_l_bracket",
                error=str(exc),
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="nx",
                action="create_l_bracket",
                error=str(exc),
            ).model_dump()

    nx_create_l_bracket = nx_create_l_bracket.with_policy(
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

    # ── create_stepped_block ────────────────────────────────────────

    @tool(
        name="nx_create_stepped_block",
        description=(
            "Submit a job to NX 12.0 bridge to create a stepped block — "
            "large base + smaller upper block united via boolean."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def nx_create_stepped_block(
        base_length_mm: float,
        base_width_mm: float,
        base_height_mm: float,
        top_length_mm: float,
        top_width_mm: float,
        top_height_mm: float,
        out_prt: str,
        out_step: str | None = None,
    ) -> dict:
        try:
            return _submit_job_and_wait(
                config=config,
                job_root=job_root,
                action="create_stepped_block",
                params={
                    "base_length": base_length_mm,
                    "base_width": base_width_mm,
                    "base_height": base_height_mm,
                    "top_length": top_length_mm,
                    "top_width": top_width_mm,
                    "top_height": top_height_mm,
                },
                out_prt=out_prt,
                out_step=out_step,
            )
        except TimeoutError as exc:
            return EngineeringActionResult(
                ok=False,
                software="nx",
                action="create_stepped_block",
                error=str(exc),
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="nx",
                action="create_stepped_block",
                error=str(exc),
            ).model_dump()

    nx_create_stepped_block = nx_create_stepped_block.with_policy(
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
            "Submit a job to NX 12.0 bridge to export an existing .prt as STEP."
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
        nx_create_block_with_hole,
        nx_create_l_bracket,
        nx_create_stepped_block,
        nx_export_step,
    ])
    return tools
