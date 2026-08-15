"""Run pre-built C++ OCCT fixtures with the conda OCCT DLL directory on PATH."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parent
BUILD_DIR = FIXTURE_DIR / "build"
OCCT_BIN = Path(r"D:\anaconda\envs\occt_cpp\Library\bin")


def run_fixture(name: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    exe = BUILD_DIR / f"{name}.exe"
    if not exe.exists():
        raise FileNotFoundError(f"fixture executable not built: {exe}")

    env = os.environ.copy()
    if OCCT_BIN.exists():
        env["PATH"] = str(OCCT_BIN) + os.pathsep + env.get("PATH", "")
        # OCCT DLLs must be co-located with the exe on Windows; the OCCT
        # manifest cannot always resolve DLLs through PATH alone.
        for dll in OCCT_BIN.glob("*.dll"):
            target = BUILD_DIR / dll.name
            if not target.exists() or target.stat().st_mtime < dll.stat().st_mtime:
                shutil.copy2(str(dll), str(target))

    return subprocess.run(
        [str(exe)],
        cwd=str(BUILD_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


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
