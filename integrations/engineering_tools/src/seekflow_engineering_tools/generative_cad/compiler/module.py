"""CompilerModule — sidecar analysis container for the GCAD compiler middle-end.

CompilerModule holds all middle-end analysis results:
  - facts: ShapeFacts store (Phase 1)
  - diagnostics: accumulated compiler issues
  - planning_report: optimization opportunities (Phase 3)

It does NOT modify CanonicalGcadDocument.
It does NOT affect canonical_graph_hash.
It does NOT alter execution behavior directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompilerModule:
    """Sidecar analysis container — inserted between canonicalize and execute.

    All fields are optional with default factories so the module can be
    constructed with just a canonical reference and progressively populated
    by analysis passes.
    """

    # Back-reference to the canonical document this module analyzes.
    # Set after construction when the canonical document is available.
    canonical: Any = None

    # ── Analysis outputs ──

    # ShapeFacts store — populated by fact propagation pass (Phase 1).
    # Will hold analysis.facts.FactStore once Phase 1 is implemented.
    facts: Any = None

    # Accumulated compiler diagnostics.
    # Each entry is a dict with: stage, code, message, severity,
    # node_id (optional), component_id (optional), details (optional).
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    # Planning report — populated by planning analysis pass (Phase 3).
    planning_report: dict[str, Any] = field(default_factory=dict)

    # Future: feature trace plan (Phase 4+).
    feature_trace_plan: list[dict[str, Any]] = field(default_factory=list)

    # Names of passes that have been executed.
    enabled_passes: list[str] = field(default_factory=list)

    def add_issue(
        self,
        *,
        stage: str,
        code: str,
        message: str,
        severity: str = "warning",
        node_id: str | None = None,
        component_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Add a compiler diagnostic issue.

        Issue format is compatible with ValidationIssue so downstream
        tooling (repair prompts, metadata) can consume both uniformly.
        """
        self.diagnostics.append({
            "stage": stage,
            "code": code,
            "message": message,
            "severity": severity,
            "node_id": node_id,
            "component_id": component_id,
            "details": details or {},
        })

    @property
    def ok(self) -> bool:
        """Return True if there are no error-severity diagnostics."""
        return not any(
            i.get("severity") == "error" for i in self.diagnostics
        )

    @property
    def warning_count(self) -> int:
        """Count of warning-severity diagnostics."""
        return sum(
            1 for i in self.diagnostics if i.get("severity") == "warning"
        )

    @property
    def error_count(self) -> int:
        """Count of error-severity diagnostics."""
        return sum(
            1 for i in self.diagnostics if i.get("severity") == "error"
        )
