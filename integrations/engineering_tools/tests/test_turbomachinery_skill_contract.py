"""Test turbomachinery-cad-ir skill contract — verifies existence and key terms."""

from pathlib import Path


SKILL_PATH = (
    Path(__file__).parent.parent / ".claude" / "skills"
    / "turbomachinery-cad-ir" / "SKILL.md"
)


def test_skill_file_exists():
    assert SKILL_PATH.exists(), f"SKILL.md not found at {SKILL_PATH}"


def test_skill_emits_cad_ir_only():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "only emits cad-ir" in text.lower() or "only emits CAD-IR" in text


def test_skill_forbids_cadquery_code():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "cadquery scripts" in text.lower() or "cadquery" in text.lower()


def test_skill_forbids_solidworks_code():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "solidworks" in text.lower()


def test_skill_mentions_safety_critical():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "safety-critical" in text.lower()


def test_skill_forbids_airworthy_claims():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "airworthy" in text.lower()
    assert "certified" in text.lower()
    assert "flight-ready" in text.lower()


def test_skill_lists_reserved_primitive_names():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "axisymmetric_turbine_disk" in text
    assert "parametric_turbine_blade" in text


def test_skill_requires_registration_check():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "registered" in text.lower()


def test_skill_requires_missing_parameter_diagnostic():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "missing-parameter" in text.lower()


def test_skill_forbids_guessing_dimensions():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "not guess" in text.lower() or "do not guess" in text.lower()


def test_skill_mentions_nxopen():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "nxopen" in text.lower()


def test_skill_mentions_apdl():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "apdl" in text.lower()


def test_skill_states_non_flight_reference_only():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "non-flight reference geometry" in text.lower()
