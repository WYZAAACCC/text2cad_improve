"""Backward-compat re-export of legacy v0.1 runner.

New code should use `seekflow_engineering_tools.generative_cad.pipeline.run`.

DEPRECATED: Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to enable.
"""

import os

if os.environ.get("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS") != "1":
    raise ImportError(
        "Legacy generative_cad.runner is disabled in production. "
        "Use seekflow_engineering_tools.generative_cad.pipeline.run. "
        "Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to allow legacy imports."
    )

from seekflow_engineering_tools.generative_cad.legacy.runner_v01 import (  # noqa: F401, E402
    GenerativeBuildContext,
    GenerativeRunResult,
    run_generative_cad_from_files,
)
