"""Backward-compat re-export of legacy v0.1 geometry preflight.

New code should use `seekflow_engineering_tools.generative_cad.validation.geometry_preflight`.
"""

from seekflow_engineering_tools.generative_cad.legacy.preflight_v01 import (  # noqa: F401
    DEFAULT_GEOMETRY_POLICY,
    run_geometry_preflight,
)
