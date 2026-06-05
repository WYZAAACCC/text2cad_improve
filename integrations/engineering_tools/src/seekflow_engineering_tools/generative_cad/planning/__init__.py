"""Planning package — read-only optimization analysis for the CAD compiler.

Phase 3: PlannerPass analyzes the canonical operation graph and ShapeFacts
to produce optimization opportunities and risk warnings. It does NOT modify
the graph or alter execution behavior.

Phase 4+: opt-in rewrite for strictly safe optimizations (batching, reorder).
"""

from seekflow_engineering_tools.generative_cad.planning.planning_report import (
    PlanningIssue,
    PlanningReport,
)
from seekflow_engineering_tools.generative_cad.planning.planner import PlannerPass

__all__ = [
    "PlanningIssue",
    "PlanningReport",
    "PlannerPass",
]
