"""Native CAD import helpers — callable without decorated tools, test-friendly."""

from __future__ import annotations

from pathlib import Path


def import_step_to_solidworks(config, input_step: str | Path, out_sldprt: str | Path) -> dict:
    """Import a STEP file into SolidWorks, save as native SLDPRT.

    Raises RuntimeError on failure. Returns {"ok": True, "files_created": [...]}.
    """
    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient

    client = SolidWorksClient(
        visible=config.solidworks_visible,
        part_template=config.solidworks_part_template,
    ).connect()

    ok = client.import_step_as_part(str(input_step), str(out_sldprt))
    if not ok:
        raise RuntimeError(f"SolidWorks STEP import failed for {out_sldprt}")

    out = Path(out_sldprt)
    if not out.exists() or out.stat().st_size < 1:
        raise RuntimeError(f"SolidWorks import reported success but SLDPRT not found: {out_sldprt}")

    return {"ok": True, "files_created": [str(out)]}


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
