"""Backward-compat re-export of legacy v0.1 graph validation.

New code should use `seekflow_engineering_tools.generative_cad.validation`.

DEPRECATED: Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to enable.
"""

import os

if os.environ.get("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS") != "1":
    raise ImportError(
        "Legacy generative_cad.graph_validation is disabled in production. "
        "Use seekflow_engineering_tools.generative_cad.validation. "
        "Set SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 to allow legacy imports."
    )

from seekflow_engineering_tools.generative_cad.legacy.graph_validation_v01 import (  # noqa: F401, E402
    GenerativeValidationIssue,
    GenerativeValidationReport,
    run_graph_validation,
    validate_base_semantics,
    validate_graph_dag,
    validate_node_ops_exist,
    validate_op_params_schema,
    validate_phase_order,
    validate_selected_bases_exist,
)
