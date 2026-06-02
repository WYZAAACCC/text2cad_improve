"""Failure taxonomy — structured error classification for authoring pipeline.

Every failure in the pipeline gets a structured code and metadata so that
metrics can track failure rates by category and repairs can target the
right stage.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AuthoringFailureCode(str, Enum):
    # Provider-level
    PROVIDER_NO_TOOL_CALL = "provider_no_tool_call"
    PROVIDER_INVALID_JSON = "provider_invalid_json"
    PROVIDER_SCHEMA_REJECTED = "provider_schema_rejected"
    PROVIDER_MULTIPLE_TOOL_CALLS = "provider_multiple_tool_calls"
    PROVIDER_WRONG_TOOL_NAME = "provider_wrong_tool_name"

    # Local schema
    LOCAL_SCHEMA_ERROR = "local_schema_error"

    # Registry
    UNKNOWN_DIALECT = "unknown_dialect"
    UNKNOWN_OP = "unknown_op"
    WRONG_OP_VERSION = "wrong_op_version"

    # Params
    PARAMS_MISSING = "params_missing"
    PARAMS_EXTRA = "params_extra"
    PARAMS_TYPE_ERROR = "params_type_error"

    # Graph
    GRAPH_REFERENCE_ERROR = "graph_reference_error"
    GRAPH_CYCLE = "graph_cycle"
    TYPE_MISMATCH = "type_mismatch"
    PHASE_ORDER_ERROR = "phase_order_error"
    OWNERSHIP_ERROR = "ownership_error"
    COMPOSITION_BOUNDARY_ERROR = "composition_boundary_error"

    # Safety / constraints
    SAFETY_MISSING = "safety_missing"
    SAFETY_DISABLED = "safety_disabled"
    CONSTRAINT_RELAXED = "constraint_relaxed"

    # Dialect / geometry
    DIALECT_SEMANTIC_ERROR = "dialect_semantic_error"
    GEOMETRY_PREFLIGHT_ERROR = "geometry_preflight_error"
    RUNTIME_GEOMETRY_ERROR = "runtime_geometry_error"

    # Metadata / inspection
    METADATA_ERROR = "metadata_error"
    STEP_INSPECTION_ERROR = "step_inspection_error"

    # Context
    CONTEXT_BUILD_ERROR = "context_build_error"
    CONTRACT_HASH_MISMATCH = "contract_hash_mismatch"
    MISSING_BASE_PACKAGE = "missing_base_package"


class AuthoringFailure(BaseModel):
    """Single authoring failure with structured metadata."""

    model_config = ConfigDict(extra="forbid")

    code: AuthoringFailureCode
    stage: str
    message: str
    path: str | None = None
    node_id: str | None = None
    dialect: str | None = None
    op: str | None = None
    retryable: bool = False
    repairable: bool = False


# ── Mapping from validation errors to failure codes ──────────────────────────


def map_validation_issue_to_failure(
    issue: dict,
    stage: str,
) -> AuthoringFailure:
    """Map a validation issue dict to a structured AuthoringFailure."""
    code_str = issue.get("code", "")
    message = issue.get("message", "")
    path = issue.get("path")
    severity = issue.get("severity", "error")

    # Map common error codes
    mapping: dict[str, AuthoringFailureCode] = {
        "unknown_dialect": AuthoringFailureCode.UNKNOWN_DIALECT,
        "unknown_op": AuthoringFailureCode.UNKNOWN_OP,
        "wrong_op_version": AuthoringFailureCode.WRONG_OP_VERSION,
        "params_missing": AuthoringFailureCode.PARAMS_MISSING,
        "params_extra": AuthoringFailureCode.PARAMS_EXTRA,
        "params_type_error": AuthoringFailureCode.PARAMS_TYPE_ERROR,
        "graph_reference_error": AuthoringFailureCode.GRAPH_REFERENCE_ERROR,
        "graph_cycle": AuthoringFailureCode.GRAPH_CYCLE,
        "type_mismatch": AuthoringFailureCode.TYPE_MISMATCH,
        "phase_order_error": AuthoringFailureCode.PHASE_ORDER_ERROR,
        "ownership_error": AuthoringFailureCode.OWNERSHIP_ERROR,
        "composition_boundary_error": AuthoringFailureCode.COMPOSITION_BOUNDARY_ERROR,
        "safety_disabled": AuthoringFailureCode.SAFETY_DISABLED,
        "constraint_relaxed": AuthoringFailureCode.CONSTRAINT_RELAXED,
        "inspection_body_count_mismatch": AuthoringFailureCode.STEP_INSPECTION_ERROR,
        "inspection_bbox_mismatch": AuthoringFailureCode.STEP_INSPECTION_ERROR,
        "pydantic_validation_failed": AuthoringFailureCode.LOCAL_SCHEMA_ERROR,
    }

    code = mapping.get(code_str)
    if code is None:
        if "param" in code_str.lower() or "params" in code_str.lower():
            code = AuthoringFailureCode.PARAMS_TYPE_ERROR
        elif "graph" in code_str.lower():
            code = AuthoringFailureCode.GRAPH_REFERENCE_ERROR
        elif "dialect" in code_str.lower():
            code = AuthoringFailureCode.DIALECT_SEMANTIC_ERROR
        else:
            code = AuthoringFailureCode.LOCAL_SCHEMA_ERROR

    # Determine if repairable
    non_repairable_codes = {
        AuthoringFailureCode.SAFETY_DISABLED,
        AuthoringFailureCode.SAFETY_MISSING,
        AuthoringFailureCode.CONSTRAINT_RELAXED,
        AuthoringFailureCode.UNKNOWN_DIALECT,
        AuthoringFailureCode.UNKNOWN_OP,
        AuthoringFailureCode.WRONG_OP_VERSION,
        AuthoringFailureCode.CONTRACT_HASH_MISMATCH,
    }

    return AuthoringFailure(
        code=code,
        stage=stage,
        message=message,
        path=path,
        retryable=(severity != "error"),
        repairable=(code not in non_repairable_codes),
    )
