"""Backward-compat re-export of legacy v0.1 metadata validation.

New code should use `seekflow_engineering_tools.generative_cad.pipeline.metadata`.

DEPRECATED: Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to enable.
"""

import os

if os.environ.get("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS") != "1":
    raise ImportError(
        "Legacy generative_cad.metadata is disabled in production. "
        "Use seekflow_engineering_tools.generative_cad.pipeline.metadata. "
        "Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to allow legacy imports."
    )

from seekflow_engineering_tools.generative_cad.legacy.metadata_v01 import (  # noqa: F401, E402
    validate_generative_metadata_v1,
)
