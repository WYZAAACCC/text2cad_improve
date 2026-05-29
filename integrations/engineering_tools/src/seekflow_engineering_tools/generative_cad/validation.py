"""Backward-compat re-export of legacy v0.1 artifact validation.

New code should use `seekflow_engineering_tools.generative_cad.pipeline.metadata`.
"""

from seekflow_engineering_tools.generative_cad.legacy.validation_v01 import (  # noqa: F401
    validate_artifact_against_generative_contract,
)
