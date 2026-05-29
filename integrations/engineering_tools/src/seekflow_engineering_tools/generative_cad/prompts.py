"""Backward-compat re-export of legacy v0.1 prompts.

New code should use `seekflow_engineering_tools.generative_cad.skills.prompts`.
"""

from seekflow_engineering_tools.generative_cad.legacy.prompts_v01 import (  # noqa: F401
    BASE_SELECTION_OUTPUT_SCHEMA,
    BASE_SELECTION_SYSTEM_PROMPT,
    FEATURE_GRAPH_SYSTEM_PROMPT,
    GENERATIVE_REPAIR_PROMPT,
)
