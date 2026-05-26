"""ANSYS 18.1 APDL batch runner."""

from __future__ import annotations

import time
from pathlib import Path

from seekflow_engineering_tools.common.process import run_subprocess


class AnsysAPDLRunner:
    """Launch ansys181.exe in batch mode for a single APDL input file."""

    def __init__(
        self,
        ansys_exe: Path,
        workspace_root: Path,
        default_timeout_s: int = 600,
        default_nproc: int = 2,
    ):
        self.ansys_exe = Path(ansys_exe)
        self.workspace_root = Path(workspace_root)
        self.default_timeout_s = default_timeout_s
        self.default_nproc = default_nproc

    def health_check(self) -> dict:
        return {
            "ansys_exe": str(self.ansys_exe),
            "exists": self.ansys_exe.exists(),
        }

    def run_apdl_file(
        self,
        input_file: Path,
        job_dir: Path,
        jobname: str,
        timeout_s: int | None = None,
        nproc: int | None = None,
    ) -> dict:
        input_file = Path(input_file)
        job_dir = Path(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)

        output_file = job_dir / f"{jobname}.out"

        if not self.ansys_exe.exists():
            raise FileNotFoundError(f"ANSYS executable not found: {self.ansys_exe}")

        timeout = timeout_s or self.default_timeout_s
        # nproc reserved for future use with -np flag when validated on target

        cmd = [
            str(self.ansys_exe),
            "-b",
            "-i", str(input_file),
            "-o", str(output_file),
            "-j", jobname,
        ]

        started = time.monotonic()
        result = run_subprocess(cmd, cwd=job_dir, timeout_s=timeout)
        elapsed_s = time.monotonic() - started

        stdout_tail = result["stdout"][-4000:] if result["stdout"] else ""
        stderr_tail = result["stderr"][-4000:] if result["stderr"] else ""

        out_text = ""
        if output_file.exists():
            out_text = _read_tail(output_file, 8000)

        has_error = (
            result["returncode"] != 0
            or "*** ERROR ***" in out_text
            or "ERROR" in stderr_tail.upper()
        )
        has_warning = "*** WARNING ***" in out_text

        return {
            "returncode": result["returncode"],
            "elapsed_s": round(elapsed_s, 3),
            "output_file": str(output_file),
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "out_tail": out_text,
            "has_error": has_error,
            "has_warning": has_warning,
        }


def _read_tail(path: Path, chars: int) -> str:
    try:
        text = path.read_text(errors="ignore")
        return text[-chars:] if len(text) > chars else text
    except Exception:
        return ""
