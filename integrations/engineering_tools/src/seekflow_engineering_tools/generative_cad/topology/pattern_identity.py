"""Pattern identity policy and instance UID — §2.6, §2.7 of the supplementary spec.

Defines:
  - PatternIdentityPolicy: ordinal / angular_anchor / explicit_instance_uid
  - PatternInstance: identity model for each pattern instance
  - PatternIdentityLedger: complete identity ledger for one pattern operation

Key principles (§2.6):
  - instance_uid MUST NOT be derived from result geometry ordering alone
  - Transform copy mode (copyGeom) MUST be recorded
  - Without explicit instance UID, symmetric equivalence classes are ambiguous

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §2.6, §2.7
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════════════════════════════════════════════
# PatternIdentityPolicy — §2.7
# ═══════════════════════════════════════════════════════════════════════════════


class PatternIdentityPolicy(str, Enum):
    """Pattern instance identity maintenance strategy (§2.7).

    ORDINAL:              The i-th instance keeps its identity, even if its
                          angular position changes due to count change.
    ANGULAR_ANCHOR:       Identity follows absolute angle. After a count
                          change, only instances at matching angles survive.
    EXPLICIT_INSTANCE_UID: The upstream design system manages each instance
                          UID explicitly. Most reliable.

    Turbine disc recommendation: EXPLICIT_INSTANCE_UID.
    If IR only supports count/start_angle, use ORDINAL as interim but
    declare the policy in metadata.
    """

    ORDINAL = "ordinal"
    ANGULAR_ANCHOR = "angular_anchor"
    EXPLICIT_INSTANCE_UID = "explicit_instance_uid"


# ═══════════════════════════════════════════════════════════════════════════════
# PatternInstance — §2.6
# ═══════════════════════════════════════════════════════════════════════════════


class PatternInstance(BaseModel):
    """Identity of a single pattern instance (§2.6).

    Each instance carries:
      - instance_uid: stable identifier (NOT derived from geometry ordering)
      - template_source_pid: the template entity's persistent ID
      - result_instance_pid: this instance's persistent ID
      - transform and copy mode: full provenance for location-based identity
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    instance_uid: str = Field(
        description="Stable instance identifier — NOT derived from geometry ordering",
    )
    ordinal: int = Field(ge=0, description="Zero-based ordinal position in pattern")
    template_source_pid: str = Field(description="Persistent ID of the template entity")
    result_instance_pid: str = Field(description="Persistent ID of this instance entity")

    # §2.6: Transform copy recording
    transform_matrix: list[float] | None = Field(
        default=None,
        description="4×4 affine transform matrix (16 floats, row-major) or None if identity",
    )
    copy_mode: str = Field(
        default="copyGeom_unknown",
        description="copyGeom=True (deep copy) | copyGeom=False (shared TShape) | unknown",
    )
    angular_position_deg: float | None = Field(
        default=None,
        description="Absolute angular position in degrees (for ANGULAR_ANCHOR policy)",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PatternIdentityLedger — §2.6
# ═══════════════════════════════════════════════════════════════════════════════


class PatternIdentityLedger(BaseModel):
    """Complete identity ledger for one pattern operation (§2.6).

    Records:
      - The pattern feature UID and identity policy
      - All individual instance identities
      - The transform copy mode used

    Provides resolve_instance() for handling policy changes (e.g. 60→61 slots).
    """

    model_config = ConfigDict(extra="forbid")

    pattern_feature_uid: str = Field(
        description="Stable feature UID of the pattern operation",
    )
    policy: PatternIdentityPolicy = Field(
        default=PatternIdentityPolicy.EXPLICIT_INSTANCE_UID,
        description="Identity maintenance strategy for this pattern",
    )
    instances: list[PatternInstance] = Field(
        default_factory=list,
        description="All instances in this pattern, in ordinal order",
    )
    copy_mode_used: str = Field(
        default="copyGeom_unknown",
        description="The transform copy mode actually used by the builder",
    )

    @property
    def instance_count(self) -> int:
        return len(self.instances)

    @property
    def has_explicit_uids(self) -> bool:
        """True when all instances have non-trivial, non-generated UIDs."""
        AUTO_PREFIXES = ("instance_", "symmetric_eq_")
        return all(
            inst.instance_uid
            and not any(inst.instance_uid.startswith(p) for p in AUTO_PREFIXES)
            for inst in self.instances
        )

    def resolve_after_count_change(
        self,
        new_count: int,
        new_policy: PatternIdentityPolicy | None = None,
    ) -> dict[str, list[str]]:
        """Determine which instances survive a pattern count change.

        This is the domain logic that decides instance identity continuity
        when the pattern count changes (e.g. 60→61 slots on a turbine disc).

        Args:
            new_count: New total number of instances.
            new_policy: Policy for the new pattern (defaults to current).

        Returns:
            Dict with keys:
              - "surviving": instance_uids that keep their identity
              - "new": instance_uids that need new identities
              - "ambiguous": instance_uids that cannot be resolved
              - "deleted": instance_uids that are removed (if new_count < old)
        """
        policy = new_policy or self.policy
        old_count = self.instance_count

        if policy == PatternIdentityPolicy.EXPLICIT_INSTANCE_UID:
            # Most reliable: survival is defined by UID persistence
            surviving = [
                inst.instance_uid for inst in self.instances[:min(old_count, new_count)]
                if inst.instance_uid
            ]
            new_instances = [
                f"instance_{i}" for i in range(old_count, new_count)
            ] if new_count > old_count else []
            deleted = [
                inst.instance_uid for inst in self.instances[new_count:]
            ] if new_count < old_count else []
            return {
                "surviving": surviving,
                "new": new_instances,
                "ambiguous": [],
                "deleted": deleted,
            }

        elif policy == PatternIdentityPolicy.ORDINAL:
            # First N instances keep identity; extras are new; dropped are deleted
            surviving = [
                inst.instance_uid for inst in self.instances[:min(old_count, new_count)]
            ]
            new_instances = [
                f"instance_{i}" for i in range(old_count, new_count)
            ] if new_count > old_count else []
            deleted = [
                inst.instance_uid for inst in self.instances[new_count:]
            ] if new_count < old_count else []
            return {
                "surviving": surviving,
                "new": new_instances,
                "ambiguous": [],
                "deleted": deleted,
            }

        elif policy == PatternIdentityPolicy.ANGULAR_ANCHOR:
            # Identity follows absolute angle — only matching angles survive.
            # Without angular_position_deg set on each instance, all become ambiguous.
            if any(inst.angular_position_deg is None for inst in self.instances):
                return {
                    "surviving": [],
                    "new": [f"instance_{i}" for i in range(new_count)],
                    "ambiguous": [inst.instance_uid for inst in self.instances],
                    "deleted": [],
                }
            # Simplified: keep instances whose ordinal < new_count
            surviving = [
                inst.instance_uid for inst in self.instances[:min(old_count, new_count)]
            ]
            return {
                "surviving": surviving,
                "new": [f"instance_{i}" for i in range(old_count, new_count)]
                       if new_count > old_count else [],
                "ambiguous": [],
                "deleted": [],
            }

        # Unknown policy → fail-closed: everything ambiguous
        return {
            "surviving": [],
            "new": [f"instance_{i}" for i in range(new_count)],
            "ambiguous": [inst.instance_uid for inst in self.instances],
            "deleted": [],
        }

    @classmethod
    def create_symmetric_equivalence_set(
        cls,
        count: int,
        template_pid: str,
        pattern_feature_uid: str,
    ) -> "PatternIdentityLedger":
        """Create a ledger for fully symmetric instances without explicit UIDs.

        §2.7: For perfectly symmetric patterns with no explicit instance UID,
        the correct result is an EQUIVALENCE SET, not individual identities.
        Each instance_uid is a placeholder that MUST be treated as ambiguous
        by downstream consumers.
        """
        instances = [
            PatternInstance(
                instance_uid=f"symmetric_eq_{i}",
                ordinal=i,
                template_source_pid=template_pid,
                result_instance_pid="pending",
            )
            for i in range(count)
        ]
        return cls(
            pattern_feature_uid=pattern_feature_uid,
            policy=PatternIdentityPolicy.ORDINAL,
            instances=instances,
            copy_mode_used="copyGeom_unknown",
        )
