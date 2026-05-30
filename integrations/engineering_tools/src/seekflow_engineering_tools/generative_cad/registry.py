"""Backward-compat re-export of legacy v0.1 BASE_REGISTRY.

New code should use `seekflow_engineering_tools.generative_cad.dialects.registry`.

DEPRECATED: Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to enable.
"""

import os

if os.environ.get("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS") != "1":
    raise ImportError(
        "Legacy generative_cad.registry is disabled in production. "
        "Use seekflow_engineering_tools.generative_cad.dialects.registry. "
        "Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to allow legacy imports."
    )

from seekflow_engineering_tools.generative_cad.legacy.registry_v01 import (  # noqa: F401, E402
    BASE_REGISTRY,
    export_base_catalog,
    get_base,
    list_bases,
    register_base,
)
