"""Smoke-test the pre-built C++ OCCT fixtures when they are available."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "name",
    ["ocaf_smoke", "tnaming_smoke", "edge_lineage", "edge_boolean", "full_edge_boolean"],
)
def test_cpp_fixture_runs(name):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "cpp_fixture"))
    try:
        from run_fixture import run_fixture
    except Exception as exc:
        pytest.skip(f"cpp fixture harness unavailable: {exc}")

    try:
        proc = run_fixture(name)
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    except (OSError, PermissionError) as exc:
        pytest.skip(f"native fixture unavailable in this environment: {exc}")
    except subprocess.TimeoutExpired:
        pytest.fail(f"{name} timed out")

    assert proc.returncode == 0, proc.stderr
