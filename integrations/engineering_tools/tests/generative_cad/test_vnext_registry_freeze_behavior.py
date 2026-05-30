"""M2: Frozen DialectRegistry behavior tests."""

import pytest


class TestDialectRegistryFreeze:
    def test_default_registry_is_frozen(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        reg = default_registry()
        assert reg.frozen is True

    def test_frozen_registry_rejects_late_registration(self):
        from seekflow_engineering_tools.generative_cad.dialects.registry_core import DialectRegistry
        from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.dialect import AXISYMMETRIC_DIALECT
        reg = DialectRegistry()
        reg.freeze()
        with pytest.raises(RuntimeError, match="frozen"):
            reg.register(AXISYMMETRIC_DIALECT)

    def test_registry_rejects_part_named_dialect(self):
        from seekflow_engineering_tools.generative_cad.dialects.registry_core import DialectRegistry
        reg = DialectRegistry()

        class FakeBearingDialect:
            dialect_id = "bearing_seat_base"
            version = "0.1.0"

            def contract(self):
                return {}

        with pytest.raises(ValueError, match="appears to name a part"):
            reg.register(FakeBearingDialect())

    def test_contract_hash_stable(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import build_default_registry
        reg1 = build_default_registry()
        reg2 = build_default_registry()
        h1 = reg1.contract_hash("axisymmetric")
        h2 = reg2.contract_hash("axisymmetric")
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_test_registry_can_be_isolated(self):
        from seekflow_engineering_tools.generative_cad.dialects.registry_core import DialectRegistry
        from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.dialect import AXISYMMETRIC_DIALECT
        reg = DialectRegistry()
        reg.register(AXISYMMETRIC_DIALECT)
        assert reg.frozen is False
        assert "axisymmetric" in reg.list_ids()
        assert "sketch_extrude" not in reg.list_ids()

    def test_compat_registry_wrappers_use_default_registry(self):
        from seekflow_engineering_tools.generative_cad.dialects import registry
        assert "axisymmetric" in registry.list_dialects()
        assert "sketch_extrude" in registry.list_dialects()
        assert "composition" in registry.list_dialects()
        d = registry.require_dialect("axisymmetric")
        assert d.dialect_id == "axisymmetric"

    def test_register_dialect_raises_in_production(self):
        from seekflow_engineering_tools.generative_cad.dialects import registry
        with pytest.raises(RuntimeError, match="disabled in production"):
            registry.register_dialect(None)

    def test_duplicate_dialect_fails(self):
        from seekflow_engineering_tools.generative_cad.dialects.registry_core import DialectRegistry
        from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.dialect import AXISYMMETRIC_DIALECT
        reg = DialectRegistry()
        reg.register(AXISYMMETRIC_DIALECT)
        with pytest.raises(ValueError, match="duplicate"):
            reg.register(AXISYMMETRIC_DIALECT)
