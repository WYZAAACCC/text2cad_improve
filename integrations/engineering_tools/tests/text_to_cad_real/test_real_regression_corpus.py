"""Test 8: Regression corpus — capability probe + basic build of all 3 fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "generative_cad"


class TestCapabilityProbe:
    """Verify capability probe works correctly."""

    def test_list_dialects(self):
        from tests.text_to_cad_real.helpers.capability_probe import (
            list_available_dialects,
        )
        dialects = list_available_dialects()
        assert isinstance(dialects, list)
        assert "axisymmetric" in dialects
        assert "sketch_extrude" in dialects
        assert "composition" in dialects

    def test_list_primitives(self):
        from tests.text_to_cad_real.helpers.capability_probe import (
            list_available_primitives,
        )
        primitives = list_available_primitives()
        assert isinstance(primitives, list)
        assert "involute_spur_gear" in primitives

    def test_capability_summary(self):
        from tests.text_to_cad_real.helpers.capability_probe import (
            capability_summary,
        )
        summary = capability_summary()
        assert "dialects" in summary
        assert "primitives" in summary
        assert "has_spur_gear_primitive" in summary
        assert summary["has_spur_gear_primitive"] is True


class TestFixtureIntegrity:
    """Verify all 3 generative CAD fixtures are valid and consistent."""

    def test_axisymmetric_minimal_fixture_valid(self):
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize,
        )
        data = json.loads((FIXTURES_DIR / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        canonical, report = validate_and_canonicalize(data)
        assert canonical is not None, f"Fixture should canonicalize: {report.model_dump()}"
        assert canonical.canonical_graph_hash, "Should have canonical_graph_hash"

    def test_sketch_extrude_minimal_fixture_valid(self):
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize,
        )
        data = json.loads((FIXTURES_DIR / "sketch_extrude_minimal.json").read_text(encoding="utf-8"))
        canonical, report = validate_and_canonicalize(data)
        assert canonical is not None, f"Fixture should canonicalize: {report.model_dump()}"

    def test_composed_disk_with_lugs_fixture_valid(self):
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize,
        )
        data = json.loads((FIXTURES_DIR / "composed_disk_with_lugs.json").read_text(encoding="utf-8"))
        canonical, report = validate_and_canonicalize(data)
        assert canonical is not None, f"Fixture should canonicalize: {report.model_dump()}"
        # Must use composition
        dialects = [d.dialect for d in canonical.selected_dialects]
        assert "composition" in dialects, "Multi-component fixture must use composition"

    def test_invalid_fixtures_fail_validation(self):
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize,
        )
        # invalid_unknown_op should fail
        data = json.loads((FIXTURES_DIR / "invalid_unknown_op.json").read_text(encoding="utf-8"))
        canonical, report = validate_and_canonicalize(data)
        assert not report.ok, "Unknown op fixture should fail validation"

        # invalid_safety_false should fail
        data = json.loads((FIXTURES_DIR / "invalid_safety_false.json").read_text(encoding="utf-8"))
        canonical, report = validate_and_canonicalize(data)
        assert not report.ok, "Safety-false fixture should fail validation"


class TestCaseSpecSchema:
    """Verify TextToCadCase schema works correctly."""

    def test_case_spec_creation(self):
        from tests.text_to_cad_real.helpers.run_text_to_cad_case import (
            TextToCadCase,
        )
        case = TextToCadCase(
            case_id="test_case",
            name="Test Case",
            prompt="Test prompt",
            expected_outcome="should_build",
            expected_route="generative_cad_ir",
            expected_dialects=["axisymmetric"],
        )
        assert case.case_id == "test_case"
        assert case.expected_outcome == "should_build"
        assert case.required_artifacts == ["step", "metadata", "artifact", "logs"]

    def test_case_spec_defaults(self):
        from tests.text_to_cad_real.helpers.run_text_to_cad_case import (
            TextToCadCase,
        )
        case = TextToCadCase(
            case_id="minimal",
            name="Minimal",
            prompt="test",
        )
        assert case.expected_outcome == "should_build"
        assert case.expected_route == "any"
        assert case.allow_repair is True
        assert case.max_repair_attempts == 2
