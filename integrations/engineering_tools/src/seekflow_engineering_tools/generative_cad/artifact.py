"""Backward-compat re-export of legacy v0.1 artifact model.

New code should use `seekflow_engineering_tools.generative_cad.pipeline.artifact`.
"""

from seekflow_engineering_tools.generative_cad.legacy.artifact_v01 import (  # noqa: F401
    CanonicalStepArtifact,
)
