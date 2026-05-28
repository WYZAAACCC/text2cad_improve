"""Test multi-family primitive registry loader."""

import pytest


def test_gear_primitives_loaded():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        list_primitive_names, get_primitive, PRIMITIVE_REGISTRY
    )
    names = list_primitive_names()
    assert "involute_spur_gear" in names
    p = get_primitive("involute_spur_gear")
    assert p is not None
    assert p.name == "involute_spur_gear"


def test_turbomachinery_family_loaded():
    """TURBOMACHINERY_PRIMITIVES has axisymmetric_turbine_disk — list should load without errors."""
    from seekflow_engineering_tools.geometry_primitives.registry import (
        list_primitive_names, _REGISTRY_LOAD_ERRORS
    )
    assert len(_REGISTRY_LOAD_ERRORS) == 0, (
        f"Registry has load errors: {_REGISTRY_LOAD_ERRORS}"
    )
    names = list_primitive_names()
    assert "axisymmetric_turbine_disk" in names
    assert "parametric_turbine_blade" not in names


def test_unknown_primitive_returns_none():
    from seekflow_engineering_tools.geometry_primitives.registry import get_primitive
    assert get_primitive("nonexistent_xyz") is None


def test_duplicate_primitive_causes_load_error(monkeypatch):
    from seekflow_engineering_tools.geometry_primitives.registry import (
        _populate_registry, _REGISTRY_LOAD_ERRORS, PRIMITIVE_REGISTRY,
        PRIMITIVE_FAMILY_MODULES,
    )
    original = list(PRIMITIVE_FAMILY_MODULES)
    # Double the gear family to cause duplicate
    monkeypatch.setattr(
        "seekflow_engineering_tools.geometry_primitives.registry.PRIMITIVE_FAMILY_MODULES",
        original + original,
    )
    _populate_registry()
    duplicate_errors = [e for e in _REGISTRY_LOAD_ERRORS if "Duplicate" in e]
    assert len(duplicate_errors) > 0
    # Restore
    monkeypatch.setattr(
        "seekflow_engineering_tools.geometry_primitives.registry.PRIMITIVE_FAMILY_MODULES",
        original,
    )
    _populate_registry()


def test_import_error_recorded(monkeypatch):
    from seekflow_engineering_tools.geometry_primitives.registry import (
        _populate_registry, _REGISTRY_LOAD_ERRORS, PRIMITIVE_FAMILY_MODULES,
    )
    broken = [
        "nonexistent.module.path:STUFF"
    ]
    monkeypatch.setattr(
        "seekflow_engineering_tools.geometry_primitives.registry.PRIMITIVE_FAMILY_MODULES",
        broken,
    )
    _populate_registry()
    assert len(_REGISTRY_LOAD_ERRORS) > 0
    assert any("ImportError" in e or "ModuleNotFoundError" in e
               for e in _REGISTRY_LOAD_ERRORS)
    # Should raise RuntimeError when unhealthy
    from seekflow_engineering_tools.geometry_primitives.registry import list_primitive_names
    with pytest.raises(RuntimeError, match="registry load errors"):
        list_primitive_names()


def test_registry_not_silently_pass_on_import_error():
    """The old code had 'except ImportError: pass' — the new code must NOT do this."""
    import inspect
    from seekflow_engineering_tools.geometry_primitives import registry as reg_mod
    source = inspect.getsource(reg_mod._populate_registry)
    assert "except ImportError:" not in source.replace(" ", ""), (
        "_populate_registry must not silently pass on ImportError"
    )


def test_non_list_export_fails(monkeypatch):
    """If a family module exports a non-list, it must be recorded as error."""
    from seekflow_engineering_tools.geometry_primitives.registry import (
        _load_definitions_from_module,
    )
    # Create a fake module that exports a string instead of a list
    import sys, types
    fake_mod = types.ModuleType("_fake_family_non_list")
    fake_mod.STUFF = "not_a_list"
    sys.modules["_fake_family_non_list"] = fake_mod
    try:
        import pytest
        with pytest.raises(TypeError, match="not a list"):
            _load_definitions_from_module("_fake_family_non_list:STUFF")
    finally:
        sys.modules.pop("_fake_family_non_list", None)


def test_non_primitive_definition_item_fails(monkeypatch):
    """If a family list contains a non-PrimitiveDefinition item, it must raise."""
    from seekflow_engineering_tools.geometry_primitives.registry import (
        _load_definitions_from_module,
    )
    import sys, types
    fake_mod = types.ModuleType("_fake_family_bad_item")
    fake_mod.STUFF = [{"not": "a primitive definition"}]
    sys.modules["_fake_family_bad_item"] = fake_mod
    try:
        import pytest
        with pytest.raises(TypeError, match="not a PrimitiveDefinition"):
            _load_definitions_from_module("_fake_family_bad_item:STUFF")
    finally:
        sys.modules.pop("_fake_family_bad_item", None)
