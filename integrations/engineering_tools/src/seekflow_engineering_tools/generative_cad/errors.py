"""Boundary error classes — normalized errors at builder/tool boundaries.

Internal dialect/handler code may use built-in ValueError/KeyError.
These errors are for external tool/builder consumption only.
"""

from __future__ import annotations


class GenerativeCadError(Exception):
    """Base for all generative CAD boundary errors."""
    code: str = "GENERATIVE_CAD_ERROR"


class ValidationFailedError(GenerativeCadError):
    code = "VALIDATION_FAILED"

    def __init__(self, stage: str, issues: list[str]) -> None:
        self.stage = stage
        self.issues = issues
        super().__init__(f"Validation failed at {stage}: {'; '.join(issues)}")


class BuildFailedError(GenerativeCadError):
    code = "BUILD_FAILED"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Generative CAD build failed: {reason}")


class UnknownDialectError(GenerativeCadError):
    code = "UNKNOWN_DIALECT"

    def __init__(self, dialect_id: str) -> None:
        self.dialect_id = dialect_id
        super().__init__(f"Unknown dialect: {dialect_id!r}")


class UnknownOperationError(GenerativeCadError):
    code = "UNKNOWN_OPERATION"

    def __init__(self, dialect: str, op: str) -> None:
        self.dialect = dialect
        self.op = op
        super().__init__(f"Unknown operation: {dialect!r}.{op!r}")


class StepExportError(GenerativeCadError):
    code = "STEP_EXPORT_FAILED"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"STEP export failed: {reason}")
