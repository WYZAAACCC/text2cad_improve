import pytest

from _main_experiment.adapters import (
    build_template_document,
    call_mcp_tool,
    load_design_families,
    load_mcp_tool_registry,
)


def test_mcp_registry_contains_expected_tools():
    tools = load_mcp_tool_registry()
    assert "check_solid_validity" in tools
    assert "check_degenerate_geometry" in tools


def test_call_unknown_mcp_tool_fails():
    with pytest.raises(KeyError):
        call_mcp_tool("__does_not_exist__")


def test_design_families_has_32_families():
    families = load_design_families()
    assert "D01" in families
    assert "D32" in families
    assert len([k for k in families if k.startswith("D")]) == 32


def test_build_basic_template_document():
    document = build_template_document(
        {
            "category": "basic",
            "od_mm": 500,
            "bore_mm": 120,
            "thick_mm": 76,
            "hub_mm": 38,
            "rim_mm": 30,
        }
    )
    assert document["schema_version"] == "g_cad_core_v0.2"
    assert document["components"]
    assert document["nodes"]
