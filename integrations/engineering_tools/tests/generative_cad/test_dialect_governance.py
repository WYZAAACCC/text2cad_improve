"""Tests for dialect governance — preventing primitive regression."""
import pytest


class TestDialectIdGovernance:
    def test_reject_part_named_dialect_id(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_dialect_id,
        )
        report = validate_dialect_id("turbine_disk_base")
        assert not report.ok
        assert any("part_named_dialect" == i.code for i in report.issues)

    def test_reject_flange_dialect(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_dialect_id,
        )
        report = validate_dialect_id("flange")
        assert not report.ok

    def test_reject_bracket_dialect(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_dialect_id,
        )
        report = validate_dialect_id("bracket_base")
        assert not report.ok

    def test_allow_axisymmetric(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_dialect_id,
        )
        report = validate_dialect_id("axisymmetric")
        assert report.ok

    def test_allow_sketch_extrude(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_dialect_id,
        )
        report = validate_dialect_id("sketch_extrude")
        assert report.ok

    def test_allow_composition(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_dialect_id,
        )
        report = validate_dialect_id("composition")
        assert report.ok


class TestOpNameGovernance:
    def test_reject_make_part_operation(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_op_name,
        )
        report = validate_op_name("make_turbine_disk")
        assert not report.ok
        assert any("make_part_operation" == i.code for i in report.issues)

    def test_reject_make_flange(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_op_name,
        )
        report = validate_op_name("make_flange")
        assert not report.ok

    def test_reject_make_bracket(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_op_name,
        )
        report = validate_op_name("make_bracket")
        assert not report.ok

    def test_reject_create_standard_prefix(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_op_name,
        )
        report = validate_op_name("create_standard_bracket")
        assert not report.ok

    def test_reject_generate_part_prefix(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_op_name,
        )
        report = validate_op_name("generate_part_flange")
        assert not report.ok

    def test_allow_revolve_profile(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_op_name,
        )
        report = validate_op_name("revolve_profile")
        assert report.ok

    def test_allow_cut_center_bore(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_op_name,
        )
        report = validate_op_name("cut_center_bore")
        assert report.ok

    def test_allow_extrude_rectangle(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_op_name,
        )
        report = validate_op_name("extrude_rectangle")
        assert report.ok

    def test_allow_boolean_union(self):
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_op_name,
        )
        report = validate_op_name("boolean_union")
        assert report.ok


class TestManifestGovernance:
    def test_typical_parts_allowed_in_manifest(self):
        """typical_parts are allowed — they are routing hints, not ops."""
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )
        reg = default_base_package_registry()
        pkg = reg.require("axisymmetric")
        # typical_parts should be present (routing hints)
        assert len(pkg.manifest.typical_parts) > 0

    def test_default_dialects_pass_governance(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            validate_dialect_governance,
        )
        reg = default_registry()
        for did in reg.list_ids():
            dialect = reg.require(did)
            report = validate_dialect_governance(dialect)
            errors = [i for i in report.issues if i.severity == "error"]
            assert len(errors) == 0, (
                f"Dialect {did} failed governance: "
                + "; ".join(i.message for i in errors)
            )

    def test_registry_enforcement_runs_in_default(self):
        """The default registry build should pass governance or raise."""
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            build_default_registry,
        )
        # Should not raise — governance passes for the default three dialects
        reg = build_default_registry()
        assert reg.frozen
        assert len(reg.list_ids()) >= 3  # at least axisymmetric, sketch_extrude, composition

    def test_axisymmetric_op_names_are_generic(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            FORBIDDEN_OP_EXACT,
        )
        reg = default_registry()
        dialect = reg.require("axisymmetric")
        for (op_name, _), _spec in dialect.op_specs().items():
            assert op_name not in FORBIDDEN_OP_EXACT, (
                f"Axisymmetric op {op_name!r} is a forbidden part op"
            )

    def test_sketch_extrude_op_names_are_generic(self):
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        from seekflow_engineering_tools.generative_cad.dialects.governance import (
            FORBIDDEN_OP_EXACT,
        )
        reg = default_registry()
        dialect = reg.require("sketch_extrude")
        for (op_name, _), _spec in dialect.op_specs().items():
            assert op_name not in FORBIDDEN_OP_EXACT, (
                f"SketchExtrude op {op_name!r} is a forbidden part op"
            )
