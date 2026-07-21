"""Persistent topology naming — stable face/edge identity across rebuilds.

Three-layer architecture:
  Layer 1: Deterministic semantic naming (producer node + semantic role)
  Layer 2: OCCT kernel shape history (Generated / Modified / Deleted)
  Layer 3: Constrained fingerprint matching (provenance + adjacency)

V3 identity model (Phase 1+): TopologyIdentityDescriptorV3 is the canonical
descriptor. v1/v2 classes are deprecated — reader preserved, writer → v3 only.

Phase 1: infrastructure skeleton — no operation handler changes.
Phase 2: topology contracts, history-aware OCP wrappers, extrude/revolve naming,
         resolution policies, constrained matcher framework, validation rules.
Phase 3+: fingerprint computation, boolean/hole/fillet wrappers, handler integration.
"""

from seekflow_engineering_tools.generative_cad.topology.contracts import (
    TopologyContract,
    TopologyOutputRole,
    get_contract,
)
from seekflow_engineering_tools.generative_cad.topology.fingerprint import (
    EdgeFingerprint,
    FaceFingerprint,
)
from seekflow_engineering_tools.generative_cad.topology.history_wrappers import (
    BooleanBuilderReport,
    HistoryAwareShapeResult,
    KernelHistoryAdapter,
    KernelHistorySnapshot,
    history_aware_extrude,
    history_aware_revolve,
    history_aware_boolean_fuse,
    history_aware_boolean_cut,
    history_aware_boolean_multi_tool,
)
from seekflow_engineering_tools.generative_cad.topology.ids import (
    PersistentTopoId,
    PersistentTopoIdV2,
    TopologyIdentityDescriptorV3,
    make_persistent_id_v2,
    make_persistent_id_v3,
    parse_persistent_id_key,
    LEGACY_V1_MARKER,
    LEGACY_V2_IRREVERSIBLE,
)
from seekflow_engineering_tools.generative_cad.topology.locator import RuntimeTopoLocator
from seekflow_engineering_tools.generative_cad.topology.shape_binding import (
    BodyTopologyMaps,
    LocatorVerification,
    ShapeBindingService,
)
from seekflow_engineering_tools.generative_cad.topology.transaction import (
    TopologyTransaction,
)
from seekflow_engineering_tools.generative_cad.topology.matcher import (
    ConstrainedTopologyMatcher,
    MatchCandidate,
    MatchConstraint,
    MatchResult,
    MatchWeights,
)
from seekflow_engineering_tools.generative_cad.topology.models import (
    BindingState,
    EntityLifecycle,
    NamedTopologySet,
    ProofClass,
    TopologyDelta,
    TopologyEntityRecord,
    TopologyRelation,
    TopologyResolution,
)
from seekflow_engineering_tools.generative_cad.topology.persistence import (
    read_topology_sidecar,
    write_topology_sidecar,
)
from seekflow_engineering_tools.generative_cad.topology.policies import (
    ConsumerPolicy,
    ResolutionQuality,
    get_consumer_policy,
    resolution_meets_quality,
)
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry
from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
    build_entity_records_from_delta,
    name_box_faces,
    name_cylinder_faces,
    name_extrude_faces,
    name_revolve_faces,
    name_sphere_faces,
)
from seekflow_engineering_tools.generative_cad.topology.kernel_validators import (
    validate_topology_contracts,
    validate_topology_references,
)
from seekflow_engineering_tools.generative_cad.topology.cae_bridge import (
    CaePreflightResult,
    CaeResolvedSet,
    cae_preflight_gate,
    resolve_named_set_to_faces,
)
from seekflow_engineering_tools.generative_cad.topology.validation import (
    validate_topology_artifact_proof,
    validate_topology_contract,
    validate_topology_reference,
    validate_topology_runtime_integrity,
)
from seekflow_engineering_tools.generative_cad.topology.design_identity import (
    DesignIdentity,
    DesignIdentityContext,
    FeatureIdentity,
    FeatureIdentityReconciler,
    IdentitySource,
)
from seekflow_engineering_tools.generative_cad.topology.kernel_identity import (
    IdentityDecision,
    IdentityRelation,
    IdentityTransferPolicy,
    KernelHistoryEdge,
    KernelRelation,
)
from seekflow_engineering_tools.generative_cad.topology.trust_certificate import (
    TopologyTrustCertificate,
    TrustLevel,
    trust_meets_quality as trust_certificate_meets_quality,
)
from seekflow_engineering_tools.generative_cad.topology.staging import (
    BuildCommitBundle,
    StagedObjectStore,
)
from seekflow_engineering_tools.generative_cad.topology.operation_adapters import (
    BooleanHistoryAdapter,
    ChamferHistoryAdapter,
    FilletHistoryAdapter,
    LoftHistoryAdapter,
    OperationHistoryAdapter,
    PrismHistoryAdapter,
    RevolveHistoryAdapter,
    SweepHistoryAdapter,
    ThickSolidHistoryAdapter,
)
from seekflow_engineering_tools.generative_cad.topology.pattern_identity import (
    PatternIdentityLedger,
    PatternIdentityPolicy,
    PatternInstance,
)
from seekflow_engineering_tools.generative_cad.topology.sidecar_canonical import (
    canonicalize_entities,
    canonicalize_float,
    canonicalize_sidecar,
    compute_integrity_hash,
)

__all__ = [
    # IDs
    "PersistentTopoId",
    "PersistentTopoIdV2",
    "TopologyIdentityDescriptorV3",
    "make_persistent_id_v2",
    "make_persistent_id_v3",
    "parse_persistent_id_key",
    "LEGACY_V1_MARKER",
    "LEGACY_V2_IRREVERSIBLE",
    # Locator
    "RuntimeTopoLocator",
    # Shape Binding
    "ShapeBindingService",
    "BodyTopologyMaps",
    "LocatorVerification",
    # Transaction
    "TopologyTransaction",
    # Models — V3 enums
    "EntityLifecycle",
    "BindingState",
    "ProofClass",
    # Models — records
    "TopologyEntityRecord",
    "TopologyDelta",
    "TopologyRelation",
    "TopologyResolution",
    "NamedTopologySet",
    # Registry
    "TopologyRegistry",
    # Persistence
    "write_topology_sidecar",
    "read_topology_sidecar",
    # Contracts (Phase 2)
    "TopologyContract",
    "TopologyOutputRole",
    "get_contract",
    # History wrappers (Phase 2)
    "HistoryAwareShapeResult",
    "KernelHistoryAdapter",
    "KernelHistorySnapshot",
    "history_aware_extrude",
    "history_aware_revolve",
    "history_aware_boolean_fuse",
    "history_aware_boolean_cut",
    "history_aware_boolean_multi_tool",
    "BooleanBuilderReport",
    # Semantic naming (Phase 1 + 2)
    "name_box_faces",
    "name_cylinder_faces",
    "name_sphere_faces",
    "name_extrude_faces",
    "name_revolve_faces",
    "build_entity_records_from_delta",
    # Fingerprints (Phase 2+)
    "FaceFingerprint",
    "EdgeFingerprint",
    # Matcher (Phase 2+)
    "ConstrainedTopologyMatcher",
    "MatchCandidate",
    "MatchConstraint",
    "MatchResult",
    "MatchWeights",
    # Policies (Phase 2)
    "ResolutionQuality",
    "ConsumerPolicy",
    "get_consumer_policy",
    "resolution_meets_quality",
    # Validation (Phase 2)
    "validate_topology_contract",
    "validate_topology_reference",
    "validate_topology_runtime_integrity",
    "validate_topology_artifact_proof",
    # Design identity (V3 supplementary spec §2.1, §2.2)
    "DesignIdentity",
    "DesignIdentityContext",
    "FeatureIdentity",
    "FeatureIdentityReconciler",
    "IdentitySource",
    # Kernel identity layering (V3 supplementary spec §2.5, §2.9)
    "IdentityDecision",
    "IdentityRelation",
    "IdentityTransferPolicy",
    "KernelHistoryEdge",
    "KernelRelation",
    # Trust certificate (V3 supplementary spec §2.11)
    "TopologyTrustCertificate",
    "TrustLevel",
    "trust_certificate_meets_quality",
    # Atomic staging (V3 supplementary spec §2.13)
    "BuildCommitBundle",
    "StagedObjectStore",
    # Operation-specific history adapters (V3 supplementary spec §2.3, §2.4)
    "BooleanHistoryAdapter",
    "ChamferHistoryAdapter",
    "FilletHistoryAdapter",
    "LoftHistoryAdapter",
    "OperationHistoryAdapter",
    "PrismHistoryAdapter",
    "RevolveHistoryAdapter",
    "SweepHistoryAdapter",
    "ThickSolidHistoryAdapter",
    # Pattern identity (V3 supplementary spec §2.6, §2.7)
    "PatternIdentityLedger",
    "PatternIdentityPolicy",
    "PatternInstance",
]
