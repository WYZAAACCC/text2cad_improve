"""Backward-compat re-export of legacy v0.1 base protocol.

New code should use `seekflow_engineering_tools.generative_cad.dialects.base`.
"""

from seekflow_engineering_tools.generative_cad.legacy.base_v01 import (  # noqa: F401
    BaseDefinition,
    OperationDefinition,
)
