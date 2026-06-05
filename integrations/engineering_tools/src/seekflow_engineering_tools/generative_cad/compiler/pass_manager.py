"""Compiler pass manager — simple sequential pass runner.

Phase 0: infrastructure only. No analysis passes registered.
Phase 1+: run_compiler_passes(module, passes) runs each pass in sequence.

Design principle: passes are pure functions that read CompilerModule
and return a (possibly enriched) CompilerModule. They do NOT modify
CanonicalGcadDocument or RuntimeContext.
"""

from __future__ import annotations

from typing import Protocol


class CompilerPass(Protocol):
    """Protocol for a single compiler analysis pass.

    Each pass receives a CompilerModule, performs read-only analysis
    on the canonical graph, and returns the module with additional
    diagnostics, facts, or reports populated.

    Passes MUST NOT:
    - Modify CompilerModule.canonical
    - Call handlers or execute geometry operations
    - Raise exceptions for non-fatal analysis findings
      (use module.add_issue() instead)
    """

    name: str

    def run(self, module: "CompilerModule") -> "CompilerModule":
        ...


def run_compiler_passes(
    module: "CompilerModule",
    passes: list["CompilerPass"],
) -> "CompilerModule":
    """Run a sequence of compiler passes on a CompilerModule.

    Passes run sequentially. If a pass raises an exception, it is
    recorded as an error diagnostic and execution stops (fail-fast).

    Args:
        module: The CompilerModule to analyze.
        passes: Ordered list of CompilerPass instances to run.

    Returns:
        The CompilerModule with all pass outputs populated.
    """
    for p in passes:
        module.enabled_passes.append(p.name)
        try:
            module = p.run(module)
        except Exception as exc:
            module.add_issue(
                stage=p.name,
                code="compiler_pass_exception",
                message=f"Compiler pass '{p.name}' failed: {exc}",
                severity="error",
            )
            # Fail-fast: stop running subsequent passes
            return module

    return module


def build_compiler_module(canonical) -> "CompilerModule":
    """Build a CompilerModule from a CanonicalGcadDocument.

    This is the entry point called from pipeline/run.py.
    In Phase 0, it creates an empty module (no passes).
    In Phase 1+, it will register and run analysis passes.

    Args:
        canonical: CanonicalGcadDocument to analyze.

    Returns:
        CompilerModule with analysis results populated.
    """
    from seekflow_engineering_tools.generative_cad.compiler.config import middle_end_enabled
    from seekflow_engineering_tools.generative_cad.compiler.module import CompilerModule

    module = CompilerModule(canonical=canonical)

    if not middle_end_enabled():
        module.add_issue(
            stage="compiler",
            code="middle_end_disabled",
            message="Compiler middle-end is disabled (SEEKFLOW_GCAD_ENABLE_MIDDLE_END=0).",
            severity="warning",
        )
        return module

    # ── Phase 1: Fact propagation ──
    from seekflow_engineering_tools.generative_cad.analysis.fact_propagation import (
        FactPropagationPass,
    )

    # ── Phase 3: Planning analysis (runs after facts are available) ──
    from seekflow_engineering_tools.generative_cad.planning.planner import (
        PlannerPass,
    )

    passes: list[CompilerPass] = [
        FactPropagationPass(),
        PlannerPass(),
    ]
    module = run_compiler_passes(module, passes)

    return module
