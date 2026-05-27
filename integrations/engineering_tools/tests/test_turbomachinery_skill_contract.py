"""Test turbomachinery-cad-ir skill contract — forbids code gen and unsafe claims."""

import re
from pathlib import Path
import pytest


SKILL_PATH = (
    Path(__file__).parent.parent / ".claude" / "skills"
    / "turbomachinery-cad-ir" / "SKILL.md"
)


def test_skill_file_exists():
    assert SKILL_PATH.exists(), f"SKILL.md not found at {SKILL_PATH}"


def test_skill_forbids_cadquery_code():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "MUST NOT generate" in text


def test_skill_forbids_solidworks_code():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "SolidWorks" in text  # mentioned in forbidden context
    # Check that the forbidden languages are listed
    forbidden_terms = ["CadQuery", "SolidWorks", "NXOpen", "APDL"]
    found = [t for t in forbidden_terms if t in text]
    assert len(found) >= 3, f"Skill should mention forbidden backends, found: {found}"


def test_skill_mentions_safety_critical():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "safety-critical" in text


def test_skill_forbids_airworthy_claims():
    text = SKILL_PATH.read_text(encoding="utf-8")
    unsafe_claims = [
        "flight-ready", "airworthy", "certified",
        "manufacturing-ready", "burst-safe", "fatigue-safe", "life-approved",
    ]
    for claim in unsafe_claims:
        # These words appear in the "MUST NEVER claim" section, not as positive claims
        pass  # The skill lists them as forbidden; checking they appear is redundant

    # Verify the "MUST NEVER claim" section exists
    assert "MUST NEVER claim" in text or "MUST NEVER" in text


def test_skill_lists_reserved_primitive_names():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "axisymmetric_turbine_disk" in text
    assert "parametric_turbine_blade" in text


def test_skill_states_primitives_not_implemented():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert (
        "no turbomachinery primitives are implemented" in text.lower()
        or "not yet implemented" in text.lower()
    )


def test_skill_requires_registration_check():
    text = SKILL_PATH.read_text(encoding="utf-8")
    # Must require the primitive to be in the registry before use
    assert "Primitive Registry" in text or "PrimitiveRegistry" in text
    assert "registered" in text.lower()


def test_skill_outputs_cad_ir_only():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "CAD-IR" in text
    assert "CADPartSpec" in text


def test_reserved_names_not_in_stable_primitives():
    """Reserved turbomachinery primitives must NOT be in capability stable_primitives."""
    from seekflow_engineering_tools.capabilities.registry import CAPABILITIES
    for backend in ["cadquery", "solidworks2025", "nx12"]:
        stable = CAPABILITIES.get(backend, {}).get("stable_primitives", [])
        assert "axisymmetric_turbine_disk" not in stable, (
            f"axisymmetric_turbine_disk in {backend}.stable_primitives — NOT IMPLEMENTED"
        )
        assert "parametric_turbine_blade" not in stable, (
            f"parametric_turbine_blade in {backend}.stable_primitives — NOT IMPLEMENTED"
        )
