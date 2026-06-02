"""Tests for BasePackage registry — registration, freeze, contract hash stability."""
import pytest


class TestBasePackageModels:
    def test_manifest_extra_forbid(self):
        from seekflow_engineering_tools.generative_cad.base_packages.models import (
            BasePackageManifest,
        )
        with pytest.raises(ValueError):
            BasePackageManifest(
                package_id="test",
                dialect_id="test",
                dialect_version="0.1.0",
                title="Test",
                summary="Test summary",
                modeling_paradigm="test",
                typical_geometry=[],
                typical_parts=[],
                main_ops=[],
                unsupported_cases=[],
                safety_notes=[],
                primitive_preferred_when=[],
                extra_field="should_be_rejected",
            )

    def test_base_package_extra_forbid(self):
        from seekflow_engineering_tools.generative_cad.base_packages.models import (
            BasePackage,
            BasePackageManifest,
        )
        manifest = BasePackageManifest(
            package_id="test",
            dialect_id="test",
            dialect_version="0.1.0",
            title="Test",
            summary="Test",
            modeling_paradigm="test",
            typical_geometry=[],
            typical_parts=[],
            main_ops=[],
            unsupported_cases=[],
            safety_notes=[],
            primitive_preferred_when=[],
        )
        with pytest.raises(ValueError):
            BasePackage(
                manifest=manifest,
                level2_usage_markdown="# Test",
                contract_hash="sha256:abc123",
                extra_field="should_be_rejected",
            )


class TestBasePackageRegistry:
    def test_register_and_get(self):
        from seekflow_engineering_tools.generative_cad.base_packages.models import (
            BasePackage,
            BasePackageManifest,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            BasePackageRegistry,
        )

        manifest = BasePackageManifest(
            package_id="test_dialect",
            dialect_id="test_dialect",
            dialect_version="0.1.0",
            title="Test",
            summary="Test",
            modeling_paradigm="test",
            typical_geometry=[],
            typical_parts=[],
            main_ops=[],
            unsupported_cases=[],
            safety_notes=[],
            primitive_preferred_when=[],
        )
        pkg = BasePackage(
            manifest=manifest,
            level2_usage_markdown="# Test",
            contract_hash="sha256:abc",
        )

        reg = BasePackageRegistry()
        reg.register(pkg)
        assert reg.get("test_dialect") is pkg
        assert reg.require("test_dialect") is pkg
        assert "test_dialect" in reg.list_ids()

    def test_duplicate_rejected(self):
        from seekflow_engineering_tools.generative_cad.base_packages.models import (
            BasePackage,
            BasePackageManifest,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            BasePackageRegistry,
        )

        manifest = BasePackageManifest(
            package_id="dup",
            dialect_id="dup",
            dialect_version="0.1.0",
            title="Dup",
            summary="Dup",
            modeling_paradigm="dup",
            typical_geometry=[],
            typical_parts=[],
            main_ops=[],
            unsupported_cases=[],
            safety_notes=[],
            primitive_preferred_when=[],
        )
        pkg = BasePackage(manifest=manifest, level2_usage_markdown="# Dup", contract_hash="sha256:abc")
        reg = BasePackageRegistry()
        reg.register(pkg)
        with pytest.raises(ValueError, match="duplicate"):
            reg.register(pkg)

    def test_package_id_must_match_dialect_id(self):
        from seekflow_engineering_tools.generative_cad.base_packages.models import (
            BasePackage,
            BasePackageManifest,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            BasePackageRegistry,
        )

        manifest = BasePackageManifest(
            package_id="wrong",
            dialect_id="right",
            dialect_version="0.1.0",
            title="Mismatch",
            summary="Mismatch",
            modeling_paradigm="mismatch",
            typical_geometry=[],
            typical_parts=[],
            main_ops=[],
            unsupported_cases=[],
            safety_notes=[],
            primitive_preferred_when=[],
        )
        pkg = BasePackage(manifest=manifest, level2_usage_markdown="# Mismatch", contract_hash="sha256:abc")
        reg = BasePackageRegistry()
        with pytest.raises(ValueError, match="must equal dialect_id"):
            reg.register(pkg)

    def test_freeze_prevents_register(self):
        from seekflow_engineering_tools.generative_cad.base_packages.models import (
            BasePackage,
            BasePackageManifest,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            BasePackageRegistry,
        )

        manifest = BasePackageManifest(
            package_id="frozen_test",
            dialect_id="frozen_test",
            dialect_version="0.1.0",
            title="Frozen",
            summary="Frozen",
            modeling_paradigm="frozen",
            typical_geometry=[],
            typical_parts=[],
            main_ops=[],
            unsupported_cases=[],
            safety_notes=[],
            primitive_preferred_when=[],
        )
        pkg = BasePackage(manifest=manifest, level2_usage_markdown="# Frozen", contract_hash="sha256:abc")
        reg = BasePackageRegistry()
        reg.register(pkg)
        reg.freeze()
        assert reg.frozen

        manifest2 = BasePackageManifest(
            package_id="frozen_test2",
            dialect_id="frozen_test2",
            dialect_version="0.1.0",
            title="Frozen2",
            summary="Frozen2",
            modeling_paradigm="frozen2",
            typical_geometry=[],
            typical_parts=[],
            main_ops=[],
            unsupported_cases=[],
            safety_notes=[],
            primitive_preferred_when=[],
        )
        pkg2 = BasePackage(manifest=manifest2, level2_usage_markdown="# Frozen2", contract_hash="sha256:abc")
        with pytest.raises(RuntimeError, match="frozen"):
            reg.register(pkg2)

    def test_require_unknown_raises_keyerror(self):
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            BasePackageRegistry,
        )
        reg = BasePackageRegistry()
        with pytest.raises(KeyError, match="unknown"):
            reg.require("nonexistent")

    def test_get_unknown_returns_none(self):
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            BasePackageRegistry,
        )
        reg = BasePackageRegistry()
        assert reg.get("nonexistent") is None

    def test_export_manifest_catalog(self):
        from seekflow_engineering_tools.generative_cad.base_packages.models import (
            BasePackage,
            BasePackageManifest,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            BasePackageRegistry,
        )

        manifest = BasePackageManifest(
            package_id="export_test",
            dialect_id="export_test",
            dialect_version="0.1.0",
            title="Export",
            summary="Export",
            modeling_paradigm="export",
            typical_geometry=[],
            typical_parts=[],
            main_ops=[],
            unsupported_cases=[],
            safety_notes=[],
            primitive_preferred_when=[],
        )
        pkg = BasePackage(manifest=manifest, level2_usage_markdown="# Export", contract_hash="sha256:abc")
        reg = BasePackageRegistry()
        reg.register(pkg)
        catalog = reg.export_manifest_catalog()
        assert catalog["catalog_version"] == "0.1.0"
        assert len(catalog["base_packages"]) == 1
        assert catalog["base_packages"][0]["package_id"] == "export_test"


class TestDefaultBasePackagesRegistered:
    def test_all_three_default_packages_registered(self):
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )
        reg = default_base_package_registry()
        ids = reg.list_ids()
        assert "axisymmetric" in ids
        assert "sketch_extrude" in ids
        assert "composition" in ids
        assert reg.frozen

    def test_base_package_id_matches_dialect_id(self):
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )
        reg = default_base_package_registry()
        for pid in reg.list_ids():
            pkg = reg.require(pid)
            assert pkg.manifest.package_id == pkg.manifest.dialect_id, (
                f"package_id {pkg.manifest.package_id!r} != dialect_id "
                f"{pkg.manifest.dialect_id!r}"
            )

    def test_base_package_contract_hash_is_stable(self):
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )
        reg = default_base_package_registry()
        for pid in reg.list_ids():
            pkg = reg.require(pid)
            assert pkg.contract_hash.startswith("sha256:"), (
                f"contract_hash for {pid} should start with 'sha256:'"
            )
            assert len(pkg.contract_hash) > len("sha256:"), (
                f"contract_hash for {pid} is too short"
            )

    def test_base_package_has_level2_usage_skill(self):
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )
        reg = default_base_package_registry()
        for pid in reg.list_ids():
            pkg = reg.require(pid)
            assert pkg.level2_usage_markdown, (
                f"BasePackage {pid} has no level2_usage_markdown"
            )
            assert "# Dialect Usage Skill:" in pkg.level2_usage_markdown, (
                f"BasePackage {pid} level2_usage_markdown missing header"
            )

    def test_base_package_has_anti_examples(self):
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )
        reg = default_base_package_registry()
        for pid in reg.list_ids():
            pkg = reg.require(pid)
            assert len(pkg.anti_examples) >= 3, (
                f"BasePackage {pid} must have at least 3 anti-examples, "
                f"got {len(pkg.anti_examples)}"
            )
