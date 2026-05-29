"""Backward-compat re-export of legacy v0.1 IR models.

New code should use `seekflow_engineering_tools.generative_cad.ir.raw` and `.ir.canonical`.
"""

from seekflow_engineering_tools.generative_cad.legacy.ir_v01 import (  # noqa: F401
    FeatureGraph,
    FeatureGraphNode,
    GenerativeCADSpec,
    LLMValidationHints,
    SafetyFlags,
    SelectedBase,
    SelectedSkill,
    SystemValidationContract,
)
