"""G-CAD Core IR v0.2 — RawGcadDocument -> CanonicalGcadDocument pipeline.

Re-exports legacy v0.1 models for backward compatibility.
"""

# Legacy v0.1 models (backward compat)
from seekflow_engineering_tools.generative_cad.ir.legacy import (  # noqa: F401
    FeatureGraph,
    FeatureGraphNode,
    GenerativeCADSpec,
    LLMValidationHints,
    SafetyFlags,
    SelectedBase,
    SelectedSkill,
    SystemValidationContract,
)

# New v0.2 models
from seekflow_engineering_tools.generative_cad.ir.raw import (  # noqa: F401
    RawComponent,
    RawConstraints,
    RawGcadDocument,
    RawNode,
    RawSafety,
    RawSelectedDialect,
    RawValueDecl,
    RawValueRef,
)
from seekflow_engineering_tools.generative_cad.ir.canonical import (  # noqa: F401
    CanonicalComponent,
    CanonicalGcadDocument,
    CanonicalNode,
    CanonicalSelectedDialect,
    CanonicalValueDecl,
    CanonicalValueRef,
)
