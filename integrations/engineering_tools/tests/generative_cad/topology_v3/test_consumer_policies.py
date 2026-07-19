"""§10.5 Consumer policies exhaustive coverage."""

import pytest

from seekflow_engineering_tools.generative_cad.topology.policies import (
    ConsumerPolicy,
    ResolutionQuality,
    _QUALITY_RANK,
    get_consumer_policy,
    resolution_meets_quality,
)


class TestConsumerPolicyExhaustive:
    def test_all_predefined_policies_exist(self):
        expected = [
            "debug_visualization", "decorative_fillet", "decorative_chamfer",
            "required_mechanical_feature", "assembly_constraint",
            "cae_load", "cae_constraint", "cae_contact", "cae_mesh_control",
            "manufacturing_output",
        ]
        for consumer in expected:
            policy = get_consumer_policy(consumer)
            assert isinstance(policy, ConsumerPolicy), f"Missing: {consumer}"

    def test_cae_contact_requires_exact_history(self):
        policy = get_consumer_policy("cae_contact")
        assert policy.minimum_quality == ResolutionQuality.EXACT_KERNEL_HISTORY
        assert not policy.allows_ambiguity

    def test_debug_allows_fingerprint(self):
        policy = get_consumer_policy("debug_visualization")
        assert policy.minimum_quality == ResolutionQuality.FINGERPRINT_UNIQUE
        assert policy.allows_ambiguity

    def test_quality_ordering(self):
        ranks = list(_QUALITY_RANK.values())
        assert ranks == sorted(ranks), "Quality ranks must be ordered"

    def test_unknown_method_raises(self):
        with pytest.raises(ValueError, match="Unknown resolution"):
            resolution_meets_quality("garbage", "exact_kernel_history")
