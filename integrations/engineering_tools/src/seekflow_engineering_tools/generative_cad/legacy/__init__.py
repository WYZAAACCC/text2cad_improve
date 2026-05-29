"""Legacy v0.1 modules — kept for backward compatibility and migration testing.

New code must not import from this package unless it is a legacy test.
Use the v0.2 `ir.raw`, `ir.canonical`, `dialects`, `validation`, `pipeline` packages instead.
"""

from seekflow_engineering_tools.generative_cad.legacy.ir_v01 import (  # noqa: F401
    FeatureGraph,
    FeatureGraphNode,
    GenerativeCADSpec,
    LLMValidationHints,
    SafetyFlags,
    SelectedBase,
    SelectedSkill,
    SystemValidationContract,
)
from seekflow_engineering_tools.generative_cad.legacy.base_v01 import (  # noqa: F401
    BaseDefinition,
    OperationDefinition,
)
from seekflow_engineering_tools.generative_cad.legacy.registry_v01 import (  # noqa: F401
    BASE_REGISTRY,
    get_base,
    list_bases,
    register_base,
    export_base_catalog,
)
from seekflow_engineering_tools.generative_cad.legacy.metadata_v01 import (  # noqa: F401
    validate_generative_metadata_v1,
)
from seekflow_engineering_tools.generative_cad.legacy.graph_validation_v01 import (  # noqa: F401
    GenerativeValidationIssue,
    GenerativeValidationReport,
    run_graph_validation,
    validate_base_semantics,
    validate_graph_dag,
    validate_node_ops_exist,
    validate_op_params_schema,
    validate_phase_order,
    validate_selected_bases_exist,
)
from seekflow_engineering_tools.generative_cad.legacy.preflight_v01 import (  # noqa: F401
    DEFAULT_GEOMETRY_POLICY,
    run_geometry_preflight,
)
from seekflow_engineering_tools.generative_cad.legacy.repair_governor_v01 import (  # noqa: F401
    ALLOWED_REPAIR_PATHS,
    FORBIDDEN_REPAIR_KEYS,
    RepairPatch,
    RepairState,
    apply_repair_patch,
    can_repair,
    check_forbidden_modifications,
    update_repair_state,
)
from seekflow_engineering_tools.generative_cad.legacy.validation_v01 import (  # noqa: F401
    validate_artifact_against_generative_contract,
)
from seekflow_engineering_tools.generative_cad.legacy.artifact_v01 import (  # noqa: F401
    CanonicalStepArtifact,
)
from seekflow_engineering_tools.generative_cad.legacy.runner_v01 import (  # noqa: F401
    GenerativeBuildContext,
    GenerativeRunResult,
    run_generative_cad_from_files,
)
from seekflow_engineering_tools.generative_cad.legacy.prompts_v01 import (  # noqa: F401
    BASE_SELECTION_OUTPUT_SCHEMA,
    BASE_SELECTION_SYSTEM_PROMPT,
    FEATURE_GRAPH_SYSTEM_PROMPT,
    GENERATIVE_REPAIR_PROMPT,
)
