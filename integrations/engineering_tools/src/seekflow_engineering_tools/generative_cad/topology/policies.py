"""Resolution quality policies — per-consumer minimum topology resolution levels.

Enforces Fail-Closed: a consumer that REQUIRES "exact" resolution MUST NOT
receive a topology entity resolved via "fingerprint_unique".

Default policies (from document §21.1):
  - Debug visualization:  FINGERPRINT_UNIQUE
  - Decorative fillet:    FINGERPRINT_UNIQUE (configurable)
  - Required mech feature: DETERMINISTIC_SEMANTIC
  - Assembly constraint:  EXACT_KERNEL_HISTORY or DETERMINISTIC_SEMANTIC
  - CAE load/constraint:  EXACT_KERNEL_HISTORY or DETERMINISTIC_SEMANTIC
  - Contact face:         EXACT_KERNEL_HISTORY
  - Manufacturing/cert:   FORBIDDEN (system currently forbids)
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ResolutionQuality(str, Enum):
    """Ordered resolution quality levels (lowest to highest).

    Resolution method from TopologyEntityRecord must be >= the consumer's
    minimum required quality.

    Quality ordering:
      UNRESOLVED < FINGERPRINT_UNIQUE < SET_EXPANSION
      < DETERMINISTIC_SEMANTIC < EXACT_KERNEL_HISTORY
    """

    UNRESOLVED = "unresolved"
    FINGERPRINT_UNIQUE = "fingerprint_unique"
    SET_EXPANSION = "set_expansion"
    DETERMINISTIC_SEMANTIC = "deterministic_semantic"
    EXACT_KERNEL_HISTORY = "exact_kernel_history"


# Ordered ranking for comparison (single source of truth)
_QUALITY_RANK: dict[str, int] = {
    "unresolved": 0,
    "fingerprint_unique": 1,
    "set_expansion": 2,
    "kernel_selected": 3,
    "deterministic_semantic": 3,
    "primitive_semantic": 4,
    "kernel_modified": 5,
    "kernel_generated": 5,
    "exact_kernel_history": 6,  # highest: requires OCCT builder history
}


def resolution_meets_quality(
    method: str,
    required: ResolutionQuality | str,
) -> bool:
    """Check if a resolution method meets the minimum required quality.

    Args:
        method: Resolution method from TopologyEntityRecord (e.g. "primitive_semantic").
        required: Minimum required quality level.

    Returns:
        True if the method's quality rank >= required rank.
    """
    method_rank = _QUALITY_RANK.get(method)
    if method_rank is None:
        raise ValueError(
            f"Unknown resolution method: {method!r}. "
            f"Valid methods: {sorted(_QUALITY_RANK.keys())}"
        )
    req_str = required.value if isinstance(required, ResolutionQuality) else required
    required_rank = _QUALITY_RANK.get(req_str)
    if required_rank is None:
        raise ValueError(
            f"Unknown resolution quality: {req_str!r}. "
            f"Valid qualities: {sorted(_QUALITY_RANK.keys())}"
        )
    return method_rank >= required_rank


class ConsumerPolicy(BaseModel):
    """Resolution quality requirement for a specific consumer type.

    Each consumer type (CAE, assembly, feature) declares its minimum
    acceptable resolution quality. The system enforces this at resolution time.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    consumer_type: Literal[
        "debug_visualization",
        "decorative_fillet",
        "decorative_chamfer",
        "required_mechanical_feature",
        "assembly_constraint",
        "cae_load",
        "cae_constraint",
        "cae_contact",
        "cae_mesh_control",
        "manufacturing_output",
    ]

    minimum_quality: ResolutionQuality = ResolutionQuality.DETERMINISTIC_SEMANTIC

    allows_ambiguity: bool = False
    allows_deleted_resolution: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-defined consumer policies
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_POLICIES: dict[str, ConsumerPolicy] = {
    "debug_visualization": ConsumerPolicy(
        consumer_type="debug_visualization",
        minimum_quality=ResolutionQuality.FINGERPRINT_UNIQUE,
        allows_ambiguity=True,
    ),
    "decorative_fillet": ConsumerPolicy(
        consumer_type="decorative_fillet",
        minimum_quality=ResolutionQuality.FINGERPRINT_UNIQUE,
        allows_ambiguity=False,
    ),
    "decorative_chamfer": ConsumerPolicy(
        consumer_type="decorative_chamfer",
        minimum_quality=ResolutionQuality.FINGERPRINT_UNIQUE,
        allows_ambiguity=False,
    ),
    "required_mechanical_feature": ConsumerPolicy(
        consumer_type="required_mechanical_feature",
        minimum_quality=ResolutionQuality.DETERMINISTIC_SEMANTIC,
        allows_ambiguity=False,
    ),
    "assembly_constraint": ConsumerPolicy(
        consumer_type="assembly_constraint",
        minimum_quality=ResolutionQuality.DETERMINISTIC_SEMANTIC,
        allows_ambiguity=False,
    ),
    "cae_load": ConsumerPolicy(
        consumer_type="cae_load",
        minimum_quality=ResolutionQuality.DETERMINISTIC_SEMANTIC,
        allows_ambiguity=False,
    ),
    "cae_constraint": ConsumerPolicy(
        consumer_type="cae_constraint",
        minimum_quality=ResolutionQuality.DETERMINISTIC_SEMANTIC,
        allows_ambiguity=False,
    ),
    "cae_contact": ConsumerPolicy(
        consumer_type="cae_contact",
        minimum_quality=ResolutionQuality.EXACT_KERNEL_HISTORY,
        allows_ambiguity=False,
    ),
    "cae_mesh_control": ConsumerPolicy(
        consumer_type="cae_mesh_control",
        minimum_quality=ResolutionQuality.DETERMINISTIC_SEMANTIC,
        allows_ambiguity=True,
    ),
    "manufacturing_output": ConsumerPolicy(
        consumer_type="manufacturing_output",
        minimum_quality=ResolutionQuality.EXACT_KERNEL_HISTORY,
        allows_ambiguity=False,
        allows_deleted_resolution=False,
    ),
}


def trust_meets_quality(
    trust_level: str,
    required: ResolutionQuality | str,
) -> bool:
    """Check if a V3 TrustLevel meets the minimum required ResolutionQuality.

    This is the bridge between the V3 trust certificate model (§2.11) and
    the existing ConsumerPolicy system. Maps TrustLevel strings to their
    equivalent ranks in _QUALITY_RANK.

    Args:
        trust_level: TrustLevel value string (e.g. "strong_kernel_history").
        required: Minimum required ResolutionQuality.

    Returns:
        True if the trust level's effective rank >= required rank.

    Mapping:
        strong_kernel_history    → rank 6 (exact_kernel_history)
        operation_semantic_exact → rank 4 (deterministic_semantic)
        fingerprint_unique       → rank 1
        set_only                 → rank 2 (set_expansion)
        ambiguous                → rank 0
        unresolved               → rank 0
    """
    _TRUST_TO_RANK = {
        "strong_kernel_history": 6,
        "operation_semantic_exact": 4,
        "fingerprint_unique": 1,
        "set_only": 2,
        "ambiguous": 0,
        "unresolved": 0,
    }
    trust_rank = _TRUST_TO_RANK.get(trust_level, 0)
    req_str = required.value if isinstance(required, ResolutionQuality) else required
    required_rank = _QUALITY_RANK.get(req_str)
    if required_rank is None:
        raise ValueError(f"Unknown resolution quality: {req_str!r}")
    return trust_rank >= required_rank


def get_consumer_policy(consumer_type: str) -> ConsumerPolicy:
    """Get the resolution quality policy for a consumer type.

    Returns a lenient default for unknown consumer types (fail-safe for
    debugging, but will reject for CAE/manufacturing).
    """
    return DEFAULT_POLICIES.get(
        consumer_type,
        ConsumerPolicy(
            consumer_type="debug_visualization",  # type: ignore[arg-type]
            minimum_quality=ResolutionQuality.DETERMINISTIC_SEMANTIC,
            allows_ambiguity=False,
        ),
    )
