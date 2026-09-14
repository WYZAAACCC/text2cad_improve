"""One error type, carrying enough structure to be acted on.

A failure in this chain has to say three things: what went wrong, which stage
was running, and whether the run could continue. A bare exception string
satisfies none of them, and the difference between `rejected` and `failed`
decides whether a resume is allowed to retry - so both live on the error
rather than being inferred from its text.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# `rejected` means the run stopped before doing anything irreversible - a bad
# parameter, a missing input, a refused domain. `failed` means something
# external was already in flight and its state is now uncertain, so a retry is
# not automatically safe. The distinction is what the orchestrator reads.
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    stage: str
    status: str = STATUS_REJECTED
    recoverable: bool = False
    details: dict = {}


class StructuralError(Exception):
    def __init__(
        self, code, message, stage, status=STATUS_REJECTED,
        recoverable=False, **details
    ):
        self.diagnostic = Diagnostic(
            code=code,
            message=message,
            stage=stage,
            status=status,
            recoverable=recoverable,
            details=details,
        )
        super().__init__(message)
