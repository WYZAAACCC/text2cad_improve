"""Standardized topology error codes (PR 11 — Repair Loop integration).

These constants replace ad-hoc strings throughout the topology system,
enabling Repair Agent structured error matching and progress tracking.
"""

# ── Contract / Spec errors ──
TOPOLOGY_CONTRACT_MISSING = "topology_contract_missing"
TOPOLOGY_HISTORY_CAPABILITY_MISMATCH = "topology_history_capability_mismatch"
TOPOLOGY_DELTA_MISSING = "topology_delta_missing"

# ── Role / Cardinality errors ──
TOPOLOGY_ROLE_MISSING = "topology_role_missing"
TOPOLOGY_CARDINALITY_MISMATCH = "topology_cardinality_mismatch"

# ── Locator / Binding errors ──
TOPOLOGY_LOCATOR_MISSING = "topology_locator_missing"
TOPOLOGY_LOCATOR_INVALID = "topology_locator_unretrievable"
TOPOLOGY_OWNER_BODY_NOT_FOUND = "topology_owner_body_not_found"
TOPOLOGY_CONTENT_HASH_MISMATCH = "topology_content_hash_mismatch"
TOPOLOGY_ENTITY_TYPE_MISMATCH = "topology_entity_type_mismatch"

# ── Reference resolution errors ──
TOPOLOGY_REF_DELETED = "topology_ref_deleted"
TOPOLOGY_REF_AMBIGUOUS = "topology_ref_ambiguous"
TOPOLOGY_REF_UNRESOLVED = "topology_ref_unresolved"
TOPOLOGY_REF_EMPTY = "topology_ref_empty"
TOPOLOGY_REF_CARDINALITY_MISMATCH = "topology_ref_cardinality_mismatch"

# ── Split / Merge errors ──
TOPOLOGY_SPLIT_NOT_ALLOWED = "topology_split_not_allowed"
TOPOLOGY_MERGE_NOT_ALLOWED = "topology_merge_not_allowed"

# ── Cache / Sidecar errors ──
TOPOLOGY_CACHE_FRAGMENT_MISMATCH = "topology_cache_fragment_mismatch"
TOPOLOGY_SIDECAR_HASH_MISMATCH = "topology_sidecar_hash_mismatch"

# ── Quality errors ──
TOPOLOGY_QUALITY_INSUFFICIENT = "topology_quality_insufficient"

__all__ = [
    "TOPOLOGY_CONTRACT_MISSING",
    "TOPOLOGY_HISTORY_CAPABILITY_MISMATCH",
    "TOPOLOGY_DELTA_MISSING",
    "TOPOLOGY_ROLE_MISSING",
    "TOPOLOGY_CARDINALITY_MISMATCH",
    "TOPOLOGY_LOCATOR_MISSING",
    "TOPOLOGY_LOCATOR_INVALID",
    "TOPOLOGY_OWNER_BODY_NOT_FOUND",
    "TOPOLOGY_CONTENT_HASH_MISMATCH",
    "TOPOLOGY_ENTITY_TYPE_MISMATCH",
    "TOPOLOGY_REF_DELETED",
    "TOPOLOGY_REF_AMBIGUOUS",
    "TOPOLOGY_REF_UNRESOLVED",
    "TOPOLOGY_REF_EMPTY",
    "TOPOLOGY_REF_CARDINALITY_MISMATCH",
    "TOPOLOGY_SPLIT_NOT_ALLOWED",
    "TOPOLOGY_MERGE_NOT_ALLOWED",
    "TOPOLOGY_CACHE_FRAGMENT_MISMATCH",
    "TOPOLOGY_SIDECAR_HASH_MISMATCH",
    "TOPOLOGY_QUALITY_INSUFFICIENT",
]