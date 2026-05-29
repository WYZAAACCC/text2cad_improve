"""Backward-compat re-export of legacy v0.1 metadata validation.

New code should use `seekflow_engineering_tools.generative_cad.pipeline.metadata`.
"""

from seekflow_engineering_tools.generative_cad.legacy.metadata_v01 import (  # noqa: F401
    validate_generative_metadata_v1,
)
