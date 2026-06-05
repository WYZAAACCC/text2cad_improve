"""Compiler middle-end configuration — feature flag and policy defaults.

Environment variable:
  SEEKFLOW_GCAD_ENABLE_MIDDLE_END=1 (default) — middle-end runs as sidecar
  SEEKFLOW_GCAD_ENABLE_MIDDLE_END=0           — middle-end disabled, old path
"""

from __future__ import annotations

import os


def middle_end_enabled() -> bool:
    """Return True if the compiler middle-end is enabled.

    Default: enabled (returns True).
    Set SEEKFLOW_GCAD_ENABLE_MIDDLE_END=0 to disable.
    """
    return os.environ.get("SEEKFLOW_GCAD_ENABLE_MIDDLE_END", "1") != "0"


# ── Policy constants (Phase 1+) ──

# When middle-end diagnostics contain errors, should runtime execution continue?
# Default: fail-closed (errors stop execution).
FAIL_ON_MIDDLE_END_ERROR: bool = True

# Minimum wall thickness margin for feasibility checks (mm).
MIN_WALL_MARGIN_MM: float = 1.0

# Maximum dim_expr recursion depth to prevent infinite loops.
MAX_DIM_EXPR_RECURSION: int = 16
