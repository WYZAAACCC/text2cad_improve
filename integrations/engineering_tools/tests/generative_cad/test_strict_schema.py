"""Tests for DeepSeek strict schema compiler."""
import pytest


class TestStrictSchemaCompiler:
    def test_all_objects_additional_properties_false(self):
        from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
            to_deepseek_strict_schema,
        )

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        result = to_deepseek_strict_schema(schema)
        assert result["additionalProperties"] is False

    def test_all_object_properties_required(self):
        from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
            to_deepseek_strict_schema,
        )

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],  # age is optional
        }
        result = to_deepseek_strict_schema(schema)
        # Both should now be required
        assert "name" in result["required"]
        assert "age" in result["required"]

    def test_optional_fields_become_nullable_anyof(self):
        from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
            to_deepseek_strict_schema,
        )

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "nickname": {"type": "string"},  # optional — not in required
            },
            "required": ["name"],
        }
        result = to_deepseek_strict_schema(schema)
        nick = result["properties"]["nickname"]
        assert "anyOf" in nick, f"Optional field should be wrapped in anyOf, got {nick}"
        types_in_anyof = [
            s.get("type") for s in nick["anyOf"] if isinstance(s, dict)
        ]
        assert "string" in types_in_anyof
        assert "null" in types_in_anyof

    def test_enum_and_const_preserved(self):
        from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
            to_deepseek_strict_schema,
        )

        schema = {
            "type": "object",
            "properties": {
                "color": {"type": "string", "enum": ["red", "green", "blue"]},
                "version": {"const": "1.0.0"},
            },
            "required": ["color", "version"],
        }
        result = to_deepseek_strict_schema(schema)
        # Required fields stay as-is (not wrapped in anyOf)
        assert result["properties"]["color"]["enum"] == ["red", "green", "blue"]
        assert result["properties"]["version"]["const"] == "1.0.0"

    def test_unsupported_min_items_stripped(self):
        from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
            to_deepseek_strict_schema,
        )

        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                },
            },
            "required": ["items"],
        }
        result = to_deepseek_strict_schema(schema)

        items_prop = result["properties"]["items"]
        assert "minItems" not in items_prop, "minItems should be stripped"
        # Should be recorded in x-local-validation
        x_local = items_prop.get("x-local-validation", {})
        assert x_local.get("minItems") == 2, f"Expected x-local-validation, got {x_local}"

    def test_unsupported_min_length_stripped(self):
        from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
            to_deepseek_strict_schema,
        )

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 3},
            },
            "required": ["name"],
        }
        result = to_deepseek_strict_schema(schema)
        name_prop = result["properties"]["name"]
        assert "minLength" not in name_prop, "minLength should be stripped"
        x_local = name_prop.get("x-local-validation", {})
        assert x_local.get("minLength") == 3

    def test_schema_compiler_is_deterministic(self):
        from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
            to_deepseek_strict_schema,
        )

        schema = {
            "type": "object",
            "properties": {
                "x": {"type": "number", "minimum": 0, "maximum": 100},
                "y": {"type": "string", "enum": ["a", "b"]},
            },
        }
        r1 = to_deepseek_strict_schema(schema)
        r2 = to_deepseek_strict_schema(schema)
        assert r1 == r2, "Compiler must be deterministic"

    def test_nested_objects_transformed(self):
        from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
            to_deepseek_strict_schema,
        )

        schema = {
            "type": "object",
            "properties": {
                "outer": {
                    "type": "object",
                    "properties": {
                        "inner": {"type": "string"},
                    },
                },
            },
            "required": ["outer"],
        }
        result = to_deepseek_strict_schema(schema)
        outer = result["properties"]["outer"]
        assert outer["additionalProperties"] is False
        assert "inner" in outer["required"]

    def test_numeric_constraints_preserved(self):
        from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
            to_deepseek_strict_schema,
        )

        schema = {
            "type": "object",
            "properties": {
                "radius": {
                    "type": "number",
                    "minimum": 0,
                    "exclusiveMaximum": 1000,
                },
            },
            "required": ["radius"],
        }
        result = to_deepseek_strict_schema(schema)
        radius = result["properties"]["radius"]
        assert radius["minimum"] == 0
        assert radius["exclusiveMaximum"] == 1000

    def test_pydantic_model_to_strict_schema(self):
        from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
            strict_schema_from_pydantic,
        )
        from pydantic import BaseModel

        class TestModel(BaseModel):
            name: str
            count: int = 0

        result = strict_schema_from_pydantic(TestModel)
        assert result["additionalProperties"] is False
        assert "name" in result["required"]
        assert "count" in result["required"]
