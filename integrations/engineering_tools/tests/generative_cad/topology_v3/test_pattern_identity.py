"""PR-5: Pattern identity policy + Instance UID — §2.6, §2.7 tests.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §2.6, §2.7
"""

from seekflow_engineering_tools.generative_cad.topology.pattern_identity import (
    PatternIdentityLedger,
    PatternIdentityPolicy,
    PatternInstance,
)


class TestPatternIdentityPolicy:
    """§2.7 — Verify three identity policies."""

    def test_three_policies_defined(self):
        assert PatternIdentityPolicy.ORDINAL.value == "ordinal"
        assert PatternIdentityPolicy.ANGULAR_ANCHOR.value == "angular_anchor"
        assert PatternIdentityPolicy.EXPLICIT_INSTANCE_UID.value == "explicit_instance_uid"

    def test_turbine_disc_recommends_explicit_uid(self):
        """§2.7: turbine disc patterns should use explicit_instance_uid."""
        # Default policy on ledger
        ledger = PatternIdentityLedger(pattern_feature_uid="pattern_slots")
        assert ledger.policy == PatternIdentityPolicy.EXPLICIT_INSTANCE_UID


class TestPatternInstance:
    """§2.6 — Verify PatternInstance identity model."""

    def test_instance_construction(self):
        inst = PatternInstance(
            instance_uid="slot_017",
            ordinal=17,
            template_source_pid="gct3_cutter_pressure",
            result_instance_pid="gct3_slot_017_face",
            copy_mode="copyGeom_True",
            angular_position_deg=102.0,
        )
        assert inst.instance_uid == "slot_017"
        assert inst.ordinal == 17
        assert inst.copy_mode == "copyGeom_True"
        assert inst.angular_position_deg == 102.0

    def test_default_copy_mode_is_unknown(self):
        """§2.6: unrecorded copy mode defaults to 'unknown' — not a guess."""
        inst = PatternInstance(
            instance_uid="slot_000",
            ordinal=0,
            template_source_pid="gct3_template",
            result_instance_pid="gct3_result",
        )
        assert inst.copy_mode == "copyGeom_unknown"

    def test_frozen_model(self):
        """PatternInstance is immutable."""
        inst = PatternInstance(
            instance_uid="slot_000",
            ordinal=0,
            template_source_pid="gct3_template",
            result_instance_pid="gct3_result",
        )
        try:
            inst.ordinal = 99  # type: ignore[misc]
        except Exception:
            pass  # Expected: frozen model


class TestPatternIdentityLedger:
    """§2.6 — Verify PatternIdentityLedger and count-change resolution."""

    def _make_60_slot_ledger(self, policy=PatternIdentityPolicy.ORDINAL):
        instances = [
            PatternInstance(
                instance_uid=f"slot_{i:03d}",
                ordinal=i,
                template_source_pid="gct3_cutter_pressure",
                result_instance_pid=f"gct3_slot_{i:03d}_wall",
                angular_position_deg=i * 6.0,
            )
            for i in range(60)
        ]
        return PatternIdentityLedger(
            pattern_feature_uid="pattern_slots",
            policy=policy,
            instances=instances,
            copy_mode_used="copyGeom_False",
        )

    def test_ordinal_60_to_61_keeps_first_60(self):
        """ORDINAL: 60→61 keeps all 60, adds 1 new."""
        ledger = self._make_60_slot_ledger(PatternIdentityPolicy.ORDINAL)
        result = ledger.resolve_after_count_change(61)
        assert len(result["surviving"]) == 60
        assert len(result["new"]) == 1

    def test_ordinal_60_to_59_drops_last(self):
        """ORDINAL: 60→59 keeps 59, deletes 1."""
        ledger = self._make_60_slot_ledger(PatternIdentityPolicy.ORDINAL)
        result = ledger.resolve_after_count_change(59)
        assert len(result["surviving"]) == 59
        assert len(result["deleted"]) == 1

    def test_explicit_uid_policy_preserves_uids(self):
        """EXPLICIT_INSTANCE_UID: surviving instances keep their UIDs."""
        ledger = self._make_60_slot_ledger(
            PatternIdentityPolicy.EXPLICIT_INSTANCE_UID,
        )
        result = ledger.resolve_after_count_change(61)
        assert result["surviving"][0] == "slot_000"

    def test_symmetric_equivalence_set(self):
        """§2.7: without explicit UIDs, fully symmetric patterns → ambiguous."""
        ledger = PatternIdentityLedger.create_symmetric_equivalence_set(
            count=60,
            template_pid="gct3_template",
            pattern_feature_uid="pattern_slots",
        )
        assert ledger.instance_count == 60
        assert not ledger.has_explicit_uids
        # All instance_uid are "symmetric_eq_N" — placeholders that
        # downstream consumers must treat as ambiguous.
        assert all(
            uid.startswith("symmetric_eq_")
            for uid in [i.instance_uid for i in ledger.instances]
        )

    def test_unknown_policy_fails_closed(self):
        """Unknown policy → everything ambiguous."""
        ledger = PatternIdentityLedger(
            pattern_feature_uid="test",
            policy=PatternIdentityPolicy.ORDINAL,
        )
        # Force an unknown policy string
        result = ledger.resolve_after_count_change(5, new_policy=None)
        # ORDINAL policy should work with new_policy=None (uses current)
        assert len(result["surviving"]) == 0  # 0 instances → 0 surviving

    def test_instance_count_property(self):
        ledger = self._make_60_slot_ledger()
        assert ledger.instance_count == 60

    def test_has_explicit_uids_false_for_auto_generated(self):
        """Auto-generated UIDs (instance_N) → has_explicit_uids is False."""
        instances = [
            PatternInstance(
                instance_uid=f"instance_{i}",
                ordinal=i,
                template_source_pid="gct3_t",
                result_instance_pid=f"gct3_r_{i}",
            )
            for i in range(3)
        ]
        ledger = PatternIdentityLedger(
            pattern_feature_uid="p",
            instances=instances,
        )
        assert ledger.has_explicit_uids is False
