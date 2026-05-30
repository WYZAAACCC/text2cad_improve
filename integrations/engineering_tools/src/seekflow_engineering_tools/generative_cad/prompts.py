"""Backward-compat re-export of legacy v0.1 prompts.

New code should use `seekflow_engineering_tools.generative_cad.skills.prompts`.

DEPRECATED: Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to enable.
"""

import os

if os.environ.get("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS") != "1":
    raise ImportError(
        "Legacy generative_cad.prompts is disabled in production. "
        "Use seekflow_engineering_tools.generative_cad.skills.prompts. "
        "Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to allow legacy imports."
    )

from seekflow_engineering_tools.generative_cad.legacy.prompts_v01 import (  # noqa: F401, E402
    BASE_SELECTION_OUTPUT_SCHEMA,
    BASE_SELECTION_SYSTEM_PROMPT,
    FEATURE_GRAPH_SYSTEM_PROMPT,
    GENERATIVE_REPAIR_PROMPT,
)
