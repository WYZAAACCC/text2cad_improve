"""Run pre-built C++ OCCT fixtures with the conda OCCT DLL directory on PATH."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parent
# OCCT version is selectable so a multi-version C++ matrix can be built and
# run per environment: set OCAF_OCCT_BIN to the target conda Library\bin and
# OCAF_FIXTURE_BUILD_DIR to that version's build directory.
BUILD_DIR = Path(os.environ.get(
    "OCAF_FIXTURE_BUILD_DIR", str(FIXTURE_DIR / "build"),
))
OCCT_BIN = Path(os.environ.get(
    "OCAF_OCCT_BIN", r"D:\anaconda\envs\occt_cpp\Library\bin",
))
DEFAULT_STAGE_ROOT = Path(
    r"C:\Users\mycomputer\.codex\visualizations\2026\08\13\019ffac8-4917-7543-ae0d-3d657f2d323a"
)


def run_fixture(name: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    exe = BUILD_DIR / f"{name}.exe"
    if not exe.exists():
        raise FileNotFoundError(f"fixture executable not built: {exe}")

    # The workspace is currently on an exFAT volume, where Windows refuses to
    # start native executables (Access Denied). Stage the exe + OCCT DLLs on
    # the system temp volume (NTFS) before running.
    stage_root = Path(os.environ.get("OCAF_FIXTURE_STAGE_DIR", str(DEFAULT_STAGE_ROOT)))
    stage_root.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(tempfile.mkdtemp(prefix="ocaf_fixture_", dir=str(stage_root)))
    staged_exe = stage_dir / exe.name
    shutil.copy2(str(exe), str(staged_exe))
    if OCCT_BIN.exists():
        for dll in OCCT_BIN.glob("*.dll"):
            shutil.copy2(str(dll), str(stage_dir / dll.name))

    try:
        return subprocess.run(
            [str(staged_exe)],
            cwd=str(stage_dir),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    finally:
        shutil.rmtree(str(stage_dir), ignore_errors=True)


def main() -> None:
    for name in ("ocaf_smoke", "tnaming_smoke", "edge_lineage", "edge_boolean"):
        try:
            proc = run_fixture(name)
            print(f"[{name}] returncode={proc.returncode}")
            if proc.stdout.strip():
                print(proc.stdout.strip())
            if proc.stderr.strip():
                print(proc.stderr.strip())
        except FileNotFoundError as exc:
            print(f"[{name}] SKIP: {exc}")
        except subprocess.TimeoutExpired:
            print(f"[{name}] TIMEOUT")


if __name__ == "__main__":
    main()
