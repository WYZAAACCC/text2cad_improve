"""Tests ensuring Base/Dialect legacy isolation — no CadQuery in base_packages, no runtime in base_packages."""
import pytest


class TestBasePackageNoRuntime:
    def test_base_package_module_has_no_cadquery_import(self):
        """base_packages must not import CadQuery or any runtime module."""
        import sys

        # Ensure the base_packages module can be imported without CadQuery
        # (CadQuery is an optional dependency)
        try:
            from seekflow_engineering_tools.generative_cad.base_packages import (
                BasePackage,
                BasePackageRegistry,
            )
        except ImportError as e:
            if "cadquery" in str(e).lower():
                pytest.fail(f"base_packages import triggers CadQuery: {e}")

    def test_base_package_module_has_no_runtime_imports(self):
        """BasePackage module should not import runtime handlers."""
        import inspect
        from seekflow_engineering_tools.generative_cad.base_packages import models as bp_models
        source = inspect.getsource(bp_models)
        forbidden = ["cadquery", "cq.Workplane", "runtime.handles", "runtime.resolve"]
        for pattern in forbidden:
            assert pattern not in source, (
                f"base_packages/models.py contains runtime import: {pattern!r}"
            )

    def test_legacy_base_import_is_blocked(self):
        """Legacy generative_cad.base must raise ImportError without env var."""
        import os
        # Ensure env var is NOT set
        old = os.environ.pop("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS", None)
        try:
            with pytest.raises(ImportError, match="disabled in production"):
                from seekflow_engineering_tools.generative_cad import base as _base_mod
                # Force reload to trigger the check
                import importlib
                importlib.reload(_base_mod)
        finally:
            if old is not None:
                os.environ["SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS"] = old

    def test_dialect_registry_knows_about_all_dialects(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        reg = default_registry()
        ids = reg.list_ids()
        assert "axisymmetric" in ids
        assert "sketch_extrude" in ids
        assert "composition" in ids

    def test_dialect_registry_catalog_matches_base_packages(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )

        d_reg = default_registry()
        bp_reg = default_base_package_registry()

        dialect_ids = set(d_reg.list_ids())
        package_ids = set(bp_reg.list_ids())
        assert dialect_ids == package_ids, (
            f"Dialect registry IDs {dialect_ids} != BasePackage IDs {package_ids}"
        )
