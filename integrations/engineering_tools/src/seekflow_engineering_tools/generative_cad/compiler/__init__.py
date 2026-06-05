"""GCAD Compiler Middle-End — v0.3.0 Phase 0.

The compiler middle-end is a sidecar analysis layer inserted between
canonicalization and runtime execution. It does NOT modify the
CanonicalGcadDocument or alter execution behavior.

Phase 0: scaffolding + feature flag (no analysis passes).
Phase 1: ShapeFacts + DimExpr schema.
Phase 2: GeometryHealth + required degradation tightening.
Phase 3: PlanningReport.
"""

from seekflow_engineering_tools.generative_cad.compiler.module import CompilerModule
from seekflow_engineering_tools.generative_cad.compiler.pass_manager import CompilerPass, run_compiler_passes
from seekflow_engineering_tools.generative_cad.compiler.config import middle_end_enabled

__all__ = [
    "CompilerModule",
    "CompilerPass",
    "run_compiler_passes",
    "middle_end_enabled",
]
