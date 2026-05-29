"""Backward-compat re-export of legacy v0.1 BASE_REGISTRY.

New code should use `seekflow_engineering_tools.generative_cad.dialects.registry`.
"""

from seekflow_engineering_tools.generative_cad.legacy.registry_v01 import (  # noqa: F401
    BASE_REGISTRY,
    export_base_catalog,
    get_base,
    list_bases,
    register_base,
)
