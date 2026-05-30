"""Backward-compat re-export of legacy v0.1 base protocol.

New code should use `seekflow_engineering_tools.generative_cad.dialects.base`.

DEPRECATED: This module imports legacy v0.1 types. Set env var
SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to enable. Production code must not use this.
"""

import os

if os.environ.get("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS") != "1":
    raise ImportError(
        "Legacy generative_cad.base is disabled in production. "
        "Use seekflow_engineering_tools.generative_cad.dialects.base. "
        "Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to allow legacy imports."
    )

from seekflow_engineering_tools.generative_cad.legacy.base_v01 import (  # noqa: F401, E402
    BaseDefinition,
    OperationDefinition,
)
