"""Tests for Level-2 usage skill generation from BasePackage + Dialect + OperationSpec."""
import pytest


class TestLevel2UsageSkillGeneration:
    def test_generate_skill_for_axisymmetric(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        from seekflow_engineering_tools.generative_cad.skills.level2_usage import (
            generate_level2_usage_skill,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )

        reg = default_registry()
        bp_reg = default_base_package_registry()
        dialect = reg.require("axisymmetric")
        pkg = bp_reg.require("axisymmetric")

        skill = generate_level2_usage_skill(
            dialect=dialect,
            package_manifest=pkg.manifest,
        )

        # Must contain essential sections
        assert "# Dialect Usage Skill: axisymmetric" in skill
        assert "## Purpose" in skill
        assert "## When to use" in skill
        assert "## When NOT to use" in skill

    def test_generated_skill_mentions_phase_order(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        from seekflow_engineering_tools.generative_cad.skills.level2_usage import (
            generate_level2_usage_skill,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )

        reg = default_registry()
        bp_reg = default_base_package_registry()
        dialect = reg.require("axisymmetric")
        pkg = bp_reg.require("axisymmetric")

        skill = generate_level2_usage_skill(dialect=dialect, package_manifest=pkg.manifest)
        assert "## Phase order" in skill
        assert "base_solid" in skill

    def test_generated_skill_mentions_operations(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        from seekflow_engineering_tools.generative_cad.skills.level2_usage import (
            generate_level2_usage_skill,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )

        reg = default_registry()
        bp_reg = default_base_package_registry()
        dialect = reg.require("axisymmetric")
        pkg = bp_reg.require("axisymmetric")

        skill = generate_level2_usage_skill(dialect=dialect, package_manifest=pkg.manifest)

        # Should mention all registered ops
        for (op_name, _), _spec in dialect.op_specs().items():
            assert op_name in skill, f"Operation {op_name!r} missing from generated skill"

    def test_generated_skill_contains_no_runner_source(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        from seekflow_engineering_tools.generative_cad.skills.level2_usage import (
            generate_level2_usage_skill,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )

        reg = default_registry()
        bp_reg = default_base_package_registry()
        dialect = reg.require("axisymmetric")
        pkg = bp_reg.require("axisymmetric")

        skill = generate_level2_usage_skill(dialect=dialect, package_manifest=pkg.manifest)

        # Must not contain runner source code patterns
        forbidden = [
            "import cadquery",
            "import CadQuery",
            "cq.Workplane",
            "subprocess",
            "def run_component",
        ]
        for pattern in forbidden:
            assert pattern not in skill, (
                f"Generated skill contains runner source: {pattern!r}"
            )

    def test_generated_skill_has_anti_patterns(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        from seekflow_engineering_tools.generative_cad.skills.level2_usage import (
            generate_level2_usage_skill,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )

        reg = default_registry()
        bp_reg = default_base_package_registry()
        dialect = reg.require("sketch_extrude")
        pkg = bp_reg.require("sketch_extrude")

        skill = generate_level2_usage_skill(dialect=dialect, package_manifest=pkg.manifest)
        assert "## Anti-patterns" in skill
        assert "make_" in skill.lower() or "part-named" in skill.lower()

    def test_skill_hash_stable(self):
        from seekflow_engineering_tools.generative_cad.skills.level2_usage import (
            compute_level2_skill_hash,
        )
        h1 = compute_level2_skill_hash("# Test skill\n")
        h2 = compute_level2_skill_hash("# Test skill\n")
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_generate_skill_for_all_dialects(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        from seekflow_engineering_tools.generative_cad.skills.level2_usage import (
            generate_level2_usage_skill,
        )
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )

        reg = default_registry()
        bp_reg = default_base_package_registry()

        for did in reg.list_ids():
            dialect = reg.require(did)
            pkg = bp_reg.require(did)
            skill = generate_level2_usage_skill(dialect=dialect, package_manifest=pkg.manifest)
            assert f"# Dialect Usage Skill: {did}" in skill
            assert len(skill) > 500, f"Skill for {did} is too short: {len(skill)} chars"
