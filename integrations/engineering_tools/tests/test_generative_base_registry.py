"""Test generative CAD base registry — legacy v0.1 tests require env flag."""

import os
os.environ["SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS"] = "1"

import pytest

from seekflow_engineering_tools.generative_cad.registry import (
    BASE_REGISTRY,
    export_base_catalog,
    get_base,
    list_bases,
    register_base,
)


class TestBaseRegistry:
    def test_axisymmetric_base_registered(self):
        assert "axisymmetric_base" in BASE_REGISTRY

    def test_sketch_extrude_base_registered(self):
        assert "sketch_extrude_base" in BASE_REGISTRY

    def test_export_base_catalog_returns_both(self):
        catalog = export_base_catalog()
        assert catalog["base_catalog_version"] == "0.1.0"
        base_ids = [b["base_id"] for b in catalog["bases"]]
        assert "axisymmetric_base" in base_ids
        assert "sketch_extrude_base" in base_ids

    def test_duplicate_base_registration_fails(self):
        base = BASE_REGISTRY["axisymmetric_base"]
        with pytest.raises(ValueError, match="Duplicate"):
            register_base(base)

    def test_part_specific_base_naming_fails(self):
        # Create a mock with forbidden part name
        class FakePartBase:
            base_id = "turbine_disk_base"
            version = "0.1.0"

            def export_manifest(self):
                return {}

        with pytest.raises(ValueError, match="appears to name a part"):
            register_base(FakePartBase())

    def test_base_id_must_end_with_base(self):
        class FakeBase:
            base_id = "not_a_valid_id"
            version = "0.1.0"

            def export_manifest(self):
                return {}

        with pytest.raises(ValueError, match="end with '_base'"):
            register_base(FakeBase())

    def test_get_base_returns_none_for_unknown(self):
        assert get_base("nonexistent_base") is None

    def test_get_base_returns_base_for_known(self):
        base = get_base("axisymmetric_base")
        assert base is not None
        assert base.base_id == "axisymmetric_base"

    def test_list_bases_returns_sorted(self):
        names = list_bases()
        assert "axisymmetric_base" in names
        assert "sketch_extrude_base" in names
        assert names == sorted(names)

    def test_every_op_in_manifest_exists_in_contract(self):
        for base_id in list_bases():
            base = BASE_REGISTRY[base_id]
            manifest = base.export_manifest()
            contract = base.export_contract()
            for op in manifest.get("main_ops", []):
                assert op in contract.get("allowed_ops", {}), (
                    f"Op {op!r} in manifest of {base_id!r} not found in contract"
                )

    def test_every_op_in_contract_exists_in_runner(self):
        for base_id in list_bases():
            base = BASE_REGISTRY[base_id]
            contract = base.export_contract()
            for op in contract.get("allowed_ops", {}):
                assert op in base.operation_definitions, (
                    f"Op {op!r} in contract of {base_id!r} not found in operation_definitions"
                )
