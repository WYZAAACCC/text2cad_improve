"""Analysis package — compiler middle-end analysis passes.

Phase 1:
  - facts.py: ShapeFacts / FactStore data models
  - fact_rules.py: Per-operation fact derivation rules (axisymmetric first)
  - fact_propagation.py: FactPropagationPass (first CompilerPass)
  - expr_eval.py: DimExpr evaluator (schema only in Phase 1)
  - semantic_specs.py: OperationSemanticSpec registry
"""

from seekflow_engineering_tools.generative_cad.analysis.facts import (
    BBoxFacts,
    FaceFact,
    FactStore,
    NumericFact,
    ShapeFacts,
)

__all__ = [
    "BBoxFacts",
    "FaceFact",
    "FactStore",
    "NumericFact",
    "ShapeFacts",
]
