"""Structured error types for OCAF topology naming operations.

Each error carries machine-readable context (lineage, revision, label entry, etc.)
so that upstream error handlers, audit logs, and CAE preflight can act on specific
failure modes rather than parsing exception messages.
"""

from __future__ import annotations

from typing import Any


class OcafError(Exception):
    """Base exception for all OCAF topology naming errors."""

    def __init__(self, message: str, **context: Any):
        super().__init__(message)
        self.context: dict[str, Any] = context

    @property
    def lineage_id(self) -> str | None:
        return self.context.get("lineage_id")

    @property
    def revision_id(self) -> str | None:
        return self.context.get("revision_id")

    @property
    def repairable(self) -> bool:
        return self.context.get("repairable", False)


# --- Path and I/O errors ---

class OcafPathEncodingError(OcafError):
    """A filesystem path could not be encoded for OCCT."""


class OcafStoreError(OcafError):
    """SaveAs or document persistence failed."""


class OcafRetrieveError(OcafError):
    """Document open/retrieve failed or returned corrupt content."""


class AtomicPublishError(OcafError):
    """Atomic publish (temp→official rename) failed."""


# --- Schema errors ---

class OcafSchemaError(OcafError):
    """DesignRoot or fixed-tag schema invariant violated."""


class StableLabelConflictError(OcafError):
    """A stable object ID maps to two different TagPaths, or a Tag is already occupied."""


# --- History capture errors ---

class HistoryCaptureError(OcafError):
    """OCCT Builder history could not be extracted."""


class HistoryIncompleteError(OcafError):
    """History was captured but is missing phases required by enforce mode."""


# --- TNaming write errors ---

class NamingWriteError(OcafError):
    """TNaming_Builder write (Generated/Modify/Delete) failed."""


# --- Selection errors ---

class SelectionCreateError(OcafError):
    """TNaming_Selector creation failed."""


class SelectionSolveError(OcafError):
    """TNaming_Selector.Solve failed."""


class SelectionAmbiguousError(OcafError):
    """Solve returned ambiguous — multiple candidates match the selection."""


class SelectionDeletedError(OcafError):
    """Solve found the selected topology was deleted in this revision."""


class SelectionSemanticError(OcafError):
    """A semantic contract (policy, entity kind, count) was violated during solve."""


# --- CAE binding errors ---

class CaeBindingPreflightError(OcafError):
    """CAE preflight check failed — required bindings missing or unresolved."""


# --- Revision management ---

class RevisionConflictError(OcafError):
    """Base revision mismatch or lineage conflict detected."""
