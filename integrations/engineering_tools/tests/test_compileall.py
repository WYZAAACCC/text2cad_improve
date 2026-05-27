"""Verify that all source files and demo_full_chain.py compile cleanly."""

import subprocess
import sys
from pathlib import Path


def test_compileall_passes():
    """Run python -m compileall on src and demo_full_chain.py."""
    project_root = Path(__file__).parent.parent
    r = subprocess.run(
        [sys.executable, "-m", "compileall", "src", "demo_full_chain.py"],
        capture_output=True, text=True, timeout=60,
        cwd=str(project_root),
    )
    assert r.returncode == 0, (
        f"compileall failed:\nSTDOUT:\n{r.stdout[:2000]}\nSTDERR:\n{r.stderr[:2000]}"
    )


def test_demo_full_chain_py_compile():
    """Verify demo_full_chain.py compiles."""
    project_root = Path(__file__).parent.parent
    r = subprocess.run(
        [sys.executable, "-m", "py_compile", "demo_full_chain.py"],
        capture_output=True, text=True, timeout=30,
        cwd=str(project_root),
    )
    assert r.returncode == 0, f"demo_full_chain.py failed to compile: {r.stderr}"
