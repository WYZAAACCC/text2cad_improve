"""Native CAD import helpers — callable without decorated tools, test-friendly.

v6.3: Added timeout protection for SolidWorks import and batch diagnostics
for large file handling.
"""

from __future__ import annotations

from pathlib import Path

# Large file threshold for diagnostic logging (bytes)
LARGE_STEP_FILE_BYTES = 3 * 1024 * 1024  # 3 MB


def import_step_to_solidworks(
    config, input_step: str | Path, out_sldprt: str | Path,
    timeout_s: int = 300,
) -> dict:
    """Import a STEP file into SolidWorks, save as native SLDPRT.

    Args:
        config: EngineeringToolsConfig with solidworks settings.
        input_step: Path to input STEP file.
        out_sldprt: Path for output SLDPRT file.
        timeout_s: Maximum time in seconds for the import (default 300s).

    Raises RuntimeError on failure.
    Returns {"ok": True, "files_created": [...], "diagnostics": {...}}.
    """
    import time

    step_path = Path(input_step)
    step_size = step_path.stat().st_size if step_path.exists() else 0
    diagnostics: dict = {"step_size_bytes": step_size}

    if step_size > LARGE_STEP_FILE_BYTES:
        diagnostics["large_file_warning"] = (
            f"STEP file is {step_size / 1e6:.1f} MB. "
            f"Large files may cause SolidWorks import timeout."
        )

    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient

    start = time.monotonic()
    client = SolidWorksClient(
        visible=config.solidworks_visible,
        part_template=config.solidworks_part_template,
    ).connect()

    try:
        ok = client.import_step_as_part(str(input_step), str(out_sldprt))
    except Exception as exc:
        elapsed = time.monotonic() - start
        raise RuntimeError(
            f"SolidWorks STEP import failed after {elapsed:.1f}s: {exc}"
        ) from exc

    elapsed = time.monotonic() - start
    diagnostics["import_time_s"] = round(elapsed, 1)

    if elapsed > timeout_s:
        raise RuntimeError(
            f"SolidWorks STEP import timed out ({elapsed:.1f}s > {timeout_s}s limit)"
        )

    if not ok:
        raise RuntimeError(
            f"SolidWorks STEP import returned failure for {out_sldprt} "
            f"(step size: {step_size / 1e3:.0f} KB, time: {elapsed:.1f}s)"
        )

    out = Path(out_sldprt)
    if not out.exists() or out.stat().st_size < 1:
        raise RuntimeError(
            f"SolidWorks import reported success but SLDPRT not found: {out_sldprt}"
        )

    diagnostics["sldprt_size_bytes"] = out.stat().st_size
    return {"ok": True, "files_created": [str(out)], "diagnostics": diagnostics}


def import_step_to_nx(config, job_root: str | Path, input_step: str | Path, out_prt: str | Path) -> dict:
    """Import a STEP file into Siemens NX, save as native PRT.

    Returns the NX job result dict.
    """
    from seekflow_engineering_tools.nx.nx_job_queue import NXJobQueue

    q = NXJobQueue(Path(job_root))
    job_id = q.submit(
        "import_step_as_prt",
        {
            "input_step": str(input_step),
            "out_prt": str(out_prt),
        },
    )
    return q.wait(job_id, timeout_s=config.nx_default_timeout_s)
