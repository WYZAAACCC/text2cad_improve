"""Backward-compat re-export of legacy v0.1 repair governor.

New code should use `seekflow_engineering_tools.generative_cad.repair.governor`.

DEPRECATED: Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to enable.
"""

import os

if os.environ.get("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS") != "1":
    raise ImportError(
        "Legacy generative_cad.repair_governor is disabled in production. "
        "Use seekflow_engineering_tools.generative_cad.repair.governor or "
        "seekflow_engineering_tools.generative_cad.repair.patch. "
        "Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to allow legacy imports."
    )

from seekflow_engineering_tools.generative_cad.legacy.repair_governor_v01 import (  # noqa: F401, E402
    ALLOWED_REPAIR_PATHS,
    FORBIDDEN_REPAIR_KEYS,
    RepairPatch,
    RepairState,
    apply_repair_patch,
    can_repair,
    check_forbidden_modifications,
    update_repair_state,
)
