"""Subprocess helpers for launching engineering software."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path


def run_subprocess(
    cmd: list[str],
    *,
    cwd: Path,
    timeout_s: float,
    env: dict[str, str] | None = None,
) -> dict:
    """Run *cmd* and return a standardised result dict.

    Returns:
        returncode, elapsed_s, stdout, stderr, cmd (for audit).
    """
    started = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=env,
    )
    elapsed_s = time.monotonic() - started

    return {
        "cmd": cmd,
        "cwd": str(cwd),
        "returncode": proc.returncode,
        "elapsed_s": round(elapsed_s, 3),
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }
