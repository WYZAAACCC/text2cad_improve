"""Backward-compat re-export of legacy v0.1 geometry preflight.

New code should use `seekflow_engineering_tools.generative_cad.validation.geometry_preflight`.

DEPRECATED: Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to enable.
"""

import os

if os.environ.get("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS") != "1":
    raise ImportError(
        "Legacy generative_cad.preflight is disabled in production. "
        "Use seekflow_engineering_tools.generative_cad.validation.geometry_preflight. "
        "Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to allow legacy imports."
    )

from seekflow_engineering_tools.generative_cad.legacy.preflight_v01 import (  # noqa: F401, E402
    DEFAULT_GEOMETRY_POLICY,
    run_geometry_preflight,
)
