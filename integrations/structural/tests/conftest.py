"""Test bootstrap.

Two paths have to be reachable. `src/` holds the package under test, so the
suite runs whether or not the editable install is present. The repository root
is found by looking for `_structural_experiment/` rather than by counting
parents from this file - a count silently points somewhere else the moment the
tests move, and the probe fixtures they read live over there.
"""
from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src"


def _find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "_structural_experiment").is_dir():
            return parent
    raise RuntimeError(
        f"could not find _structural_experiment above {Path(__file__).resolve()}"
    )


REPO_ROOT = _find_repo_root()
STRUCTURAL_EXPERIMENT = REPO_ROOT / "_structural_experiment"
PROBES = STRUCTURAL_EXPERIMENT / "probes"

for entry in (str(SRC), str(STRUCTURAL_EXPERIMENT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)
