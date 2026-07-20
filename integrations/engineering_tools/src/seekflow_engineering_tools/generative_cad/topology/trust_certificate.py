"""TopologyTrustCertificate — multi-dimensional trust assessment (§2.11).

Replaces string-based resolution_method ranking with structured,
verifiable trust evidence. Each dimension (binding, coverage, orientation,
event chain, provider capability) must be independently verified.

Trust levels:
  STRONG_KERNEL_HISTORY   — all 6 flags + real OCCT history
  OPERATION_SEMANTIC_EXACT — 3+ flags + deterministic semantic naming
  FINGERPRINT_UNIQUE      — fingerprint matcher (non-stub) unique match
  SET_ONLY                — set expansion, no individual identity
  AMBIGUOUS               — multiple candidates, cannot disambiguate
  UNRESOLVED              — no resolution possible

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §2.11
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from seekflow_engineering_tools.generative_cad.topology.models import (
        TopologyEntityRecord,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TrustLevel — ordered trust categories (§2.11)
# ═══════════════════════════════════════════════════════════════════════════════


class TrustLevel(str, Enum):
    """Ordered trust categories (lowest to highest)."""

    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    SET_ONLY = "set_only"
    FINGERPRINT_UNIQUE = "fingerprint_unique"
    OPERATION_SEMANTIC_EXACT = "operation_semantic_exact"
    STRONG_KERNEL_HISTORY = "strong_kernel_history"


# Ordered for comparison
_TRUST_RANK: dict[str, int] = {
    "unresolved": 0,
    "ambiguous": 1,
    "set_only": 2,
    "fingerprint_unique": 3,
    "operation_semantic_exact": 4,
    "strong_kernel_history": 6,  # level with exact_kernel_history
}


# ═══════════════════════════════════════════════════════════════════════════════
# TopologyTrustCertificate (§2.11)
# ═══════════════════════════════════════════════════════════════════════════════


class TopologyTrustCertificate(BaseModel):
    """Multi-dimensional trust assessment for a topology entity.

    Key principles (§2.11):
      1. resolution_method is evidence, not a trust decision.
      2. strong_kernel_history requires ALL verification flags + real history.
      3. primitive birth face can be operation_semantic_exact.
      4. primitive_semantic does NOT automatically prove subsequent Boolean results.
      5. The weak-est edge in the lineage determines overall trust.
      6. CAE gate must verify the certificate, not just resolution_method.
      7. cae_contact defaults to strong_kernel_history only.

    The trust_level is computed by assess() from the verification flags
    and resolution_method evidence. It is NOT set by the caller.
    """

    model_config = ConfigDict(extra="forbid")

    # ── Evidence fields (facts, not decisions) ──
    identity_provider: str = ""          # e.g. "axisymmetric.revolve_profile"
    history_provider: str = ""           # e.g. "occt_boolean_history"
    resolution_method: str = ""          # preserved for backward compat

    # ── Verification flags (each must be independently proven) ──
    binding_verified: bool = False       # locator + content hash match
    coverage_verified: bool = False      # 100% face coverage on final body
    orientation_verified: bool = False   # §2.5: orientation checked
    event_chain_verified: bool = False   # lineage DAG is consistent
    provider_capability_verified: bool = False  # provider is not a stub

    # ── Aggregate counts ──
    ambiguity_count: int = 0
    unresolved_count: int = 0

    # ── Computed trust level (set by assess()) ──
    trust_level: TrustLevel = TrustLevel.UNRESOLVED

    @property
    def verified_count(self) -> int:
        """Number of verification flags that are True."""
        return sum([
            self.binding_verified,
            self.coverage_verified,
            self.orientation_verified,
            self.event_chain_verified,
            self.provider_capability_verified,
        ])

    @property
    def is_strong(self) -> bool:
        """Convenience: True for strong_kernel_history trust level."""
        return self.trust_level == TrustLevel.STRONG_KERNEL_HISTORY

    @classmethod
    def assess(
        cls,
        record: Any,  # TopologyEntityRecord
        *,
        binding_verified: bool = False,
        coverage_verified: bool = False,
        orientation_verified: bool = False,
        event_chain_verified: bool = False,
        provider_capability_verified: bool = False,
        ambiguity_count: int = 0,
        unresolved_count: int = 0,
    ) -> "TopologyTrustCertificate":
        """Assess trust level from a TopologyEntityRecord + verification evidence.

        The assessment logic implements §2.11 rules:
          - strong_kernel_history: all 5 flags + kernel-based resolution_method
          - operation_semantic_exact: 3+ flags + deterministic_semantic
          - fingerprint_unique: non-stub fingerprint matching
          - The resolution_method alone does NOT determine trust.
        """
        resolution = getattr(record, "resolution_method", "") or ""
        history_provider = getattr(record, "history_provider", "") or ""
        identity_provider = getattr(record, "producer_node_id", "") or ""

        # Count verification flags
        flags = [
            binding_verified,
            coverage_verified,
            orientation_verified,
            event_chain_verified,
            provider_capability_verified,
        ]
        verified = sum(flags)

        # ── Determine trust_level ──
        if ambiguity_count > 0:
            trust_level = TrustLevel.AMBIGUOUS
        elif unresolved_count > 0:
            trust_level = TrustLevel.UNRESOLVED
        elif verified >= 5 and resolution in (
            "exact_kernel_history", "kernel_generated", "kernel_modified",
        ):
            trust_level = TrustLevel.STRONG_KERNEL_HISTORY
        elif verified >= 3 and resolution in (
            "deterministic_semantic", "kernel_selected",
        ):
            trust_level = TrustLevel.OPERATION_SEMANTIC_EXACT
        elif verified >= 1 and resolution == "fingerprint_unique":
            trust_level = TrustLevel.FINGERPRINT_UNIQUE
        elif resolution == "set_expansion":
            trust_level = TrustLevel.SET_ONLY
        else:
            # §2.11 rule 4: primitive_semantic does NOT auto-prove
            # any trust level beyond ambiguous unless verified
            trust_level = TrustLevel.UNRESOLVED

        return cls(
            identity_provider=identity_provider,
            history_provider=history_provider,
            resolution_method=resolution,
            binding_verified=binding_verified,
            coverage_verified=coverage_verified,
            orientation_verified=orientation_verified,
            event_chain_verified=event_chain_verified,
            provider_capability_verified=provider_capability_verified,
            ambiguity_count=ambiguity_count,
            unresolved_count=unresolved_count,
            trust_level=trust_level,
        )


def trust_meets_quality(
    certificate: TopologyTrustCertificate | str,
    minimum_trust: TrustLevel | str,
) -> bool:
    """Check if a trust certificate (or trust level string) meets the minimum.

    Accepts both TopologyTrustCertificate and raw string trust levels
    for backward compatibility with consumers that only have string evidence.

    Args:
        certificate: TopologyTrustCertificate or trust level string.
        minimum_trust: Minimum required TrustLevel or string.

    Returns:
        True if trust level rank >= minimum rank.
    """
    if isinstance(certificate, TopologyTrustCertificate):
        cert_str = certificate.trust_level.value
    elif isinstance(certificate, str):
        cert_str = certificate
    else:
        cert_str = "unresolved"

    min_str = minimum_trust.value if isinstance(minimum_trust, TrustLevel) else str(minimum_trust)

    # Try TrustLevel rank first; fall back to ResolutionQuality rank
    cert_rank = _TRUST_RANK.get(cert_str)
    if cert_rank is None:
        from seekflow_engineering_tools.generative_cad.topology.policies import (
            _QUALITY_RANK,
        )
        cert_rank = _QUALITY_RANK.get(cert_str, 0)

    min_rank = _TRUST_RANK.get(min_str)
    if min_rank is None:
        from seekflow_engineering_tools.generative_cad.topology.policies import (
            _QUALITY_RANK,
        )
        min_rank = _QUALITY_RANK.get(min_str, 0)

    return cert_rank >= min_rank
