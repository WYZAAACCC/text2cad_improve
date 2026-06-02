"""Tests for tool_schema_compiler — no hard-coded op descriptions, spec-driven versions."""
import pytest


class TestToolSchemaCompiler:
    def test_compiler_produces_valid_schema(self):
        from seekflow_engineering_tools.generative_cad.skills.tool_schema_compiler import (
            compile_level2_tool_schema,
        )

        schema = compile_level2_tool_schema()
        assert "$defs" in schema
        assert "properties" in schema
        # Must have nodes
        assert "nodes" in schema.get("properties", {})

    def test_tool_uses_spec_op_version(self):
        """op_version must come from OperationSpec.op_version, not hard-coded '1.0.0'."""
        from seekflow_engineering_tools.generative_cad.skills.tool_schema_compiler import (
            compile_level2_tool_schema,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )

        schema = compile_level2_tool_schema()
        nodes_prop = schema.get("properties", {}).get("nodes", {})
        items = nodes_prop.get("items", {})
        any_of = items.get("anyOf", [])

        reg = default_registry()
        for variant in any_of:
            title = variant.get("title", "")
            props = variant.get("properties", {})
            op_version_const = props.get("op_version", {}).get("const")

            if op_version_const:
                # Verify it matches the actual OperationSpec version
                dialect_id = props.get("dialect", {}).get("const", "")
                op_name = props.get("op", {}).get("const", "")
                if dialect_id and op_name:
                    d = reg.get(dialect_id)
                    if d:
                        spec = d.get_op_spec(op_name, op_version_const)
                        assert spec.op_version == op_version_const, (
                            f"Variant {title}: schema op_version={op_version_const!r} "
                            f"but spec.op_version={spec.op_version!r}"
                        )

    def test_tool_no_hardcoded_op_descriptions(self):
        """Tool schema compiler should not contain the old OP_DESCRIPTIONS dict."""
        from seekflow_engineering_tools.generative_cad.skills import tool_schema_compiler
        import inspect

        source = inspect.getsource(tool_schema_compiler)
        # The compiler should NOT contain a dict assignment named OP_DESCRIPTIONS
        # (appearing in a docstring comment is fine)
        assert "OP_DESCRIPTIONS =" not in source, (
            "tool_schema_compiler must not define OP_DESCRIPTIONS dict"
        )
        assert "OP_DESCRIPTIONS:" not in source, (
            "tool_schema_compiler must not define OP_DESCRIPTIONS type annotation"
        )

    def test_tool_schema_uses_params_model_schema(self):
        from seekflow_engineering_tools.generative_cad.skills.tool_schema_compiler import (
            compile_level2_tool_schema,
        )

        schema = compile_level2_tool_schema()
        defs = schema.get("$defs", {})

        # Should have per-op params schemas
        params_defs = {k: v for k, v in defs.items() if k.endswith("_params")}
        assert len(params_defs) > 0, "Expected per-op params $defs"

        # Each params def should have properties
        for name, ps in params_defs.items():
            assert "properties" in ps, f"Params def {name} missing 'properties'"

    def test_tool_schema_rejects_unknown_dialect_by_enum(self):
        from seekflow_engineering_tools.generative_cad.skills.tool_schema_compiler import (
            compile_level2_tool_schema,
        )

        schema = compile_level2_tool_schema()
        defs = schema.get("$defs", {})

        # Find the RawSelectedDialect def (has dialect + version props)
        dialect_enum = None
        for def_name, def_schema in defs.items():
            props = def_schema.get("properties", {})
            if set(props.keys()) == {"dialect", "version"}:
                dialect_enum = props.get("dialect", {}).get("enum", [])
                break

        assert dialect_enum is not None, "Could not find RawSelectedDialect schema"
        assert "nonexistent_dialect" not in dialect_enum, (
            "Unknown dialect should not be in enum"
        )
        assert "axisymmetric" in dialect_enum

    def test_tool_schema_variants_match_registered_ops(self):
        from seekflow_engineering_tools.generative_cad.skills.tool_schema_compiler import (
            compile_level2_tool_schema,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )

        schema = compile_level2_tool_schema()
        nodes_prop = schema.get("properties", {}).get("nodes", {})
        any_of = nodes_prop.get("items", {}).get("anyOf", [])

        reg = default_registry()
        expected_count = sum(
            len(d.op_specs()) for d in (reg.require(dn) for dn in reg.list_ids())
        )
        # Each op should have a variant
        assert len(any_of) >= expected_count, (
            f"Expected at least {expected_count} op variants, got {len(any_of)}"
        )

    def test_build_level2_tool_from_compiler(self):
        from seekflow_engineering_tools.generative_cad.skills.tool_schema_compiler import (
            build_level2_tool_from_compiler,
        )

        tool = build_level2_tool_from_compiler()
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "generate_raw_gcad_document"
        assert "parameters" in tool["function"]
