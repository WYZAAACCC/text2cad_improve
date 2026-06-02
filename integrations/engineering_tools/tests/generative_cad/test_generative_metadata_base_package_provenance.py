"""Tests for metadata provenance — BasePackage / Level-2 Skill / tool schema hashes."""
import pytest


class TestMetadataProvenance:
    def test_contract_hash_computation(self):
        from seekflow_engineering_tools.generative_cad.ir.hashing import contract_hash

        h1 = contract_hash({"test": "data"})
        h2 = contract_hash({"test": "data"})
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_contract_hash_differs_for_different_data(self):
        from seekflow_engineering_tools.generative_cad.ir.hashing import contract_hash

        h1 = contract_hash({"test": "data1"})
        h2 = contract_hash({"test": "data2"})
        assert h1 != h2

    def test_base_package_contract_hash_is_in_package(self):
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )
        reg = default_base_package_registry()
        for pid in reg.list_ids():
            pkg = reg.require(pid)
            assert pkg.contract_hash
            assert isinstance(pkg.contract_hash, str)
            assert len(pkg.contract_hash) > 10

    def test_level2_usage_skill_hash_available(self):
        from seekflow_engineering_tools.generative_cad.skills.level2_usage import (
            compute_level2_skill_hash,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )
        reg = default_base_package_registry()
        for pid in reg.list_ids():
            pkg = reg.require(pid)
            skill_hash = compute_level2_skill_hash(pkg.level2_usage_markdown)
            assert skill_hash.startswith("sha256:")
            # Same skill → same hash
            assert skill_hash == compute_level2_skill_hash(pkg.level2_usage_markdown)

    def test_authoring_context_packer_includes_manifests(self):
        from seekflow_engineering_tools.generative_cad.skills.authoring_context import (
            pack_authoring_context,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )

        bp_reg = default_base_package_registry()
        manifests = {pid: bp_reg.require(pid).manifest for pid in bp_reg.list_ids()}
        skills = {pid: bp_reg.require(pid).level2_usage_markdown for pid in bp_reg.list_ids()}

        packed = pack_authoring_context(
            package_manifests=manifests,
            usage_skills=skills,
        )
        assert "## Selected BasePackage Manifests" in packed
        assert "## Dialect Usage Skills" in packed

    def test_authoring_context_truncates_long_content(self):
        from seekflow_engineering_tools.generative_cad.skills.authoring_context import (
            pack_authoring_context,
        )

        manifests = {"test": {
            "title": "T" * 5000,
            "modeling_paradigm": "test",
            "typical_geometry": [],
            "typical_parts": [],
            "unsupported_cases": [],
        }}
        skills = {"test": "# " + "X" * 10000}

        packed = pack_authoring_context(
            package_manifests=manifests,
            usage_skills=skills,
            max_manifest_chars=500,
            max_skill_chars=500,
        )
        # Should not raise, and should be truncated
        assert len(packed) < 20000
