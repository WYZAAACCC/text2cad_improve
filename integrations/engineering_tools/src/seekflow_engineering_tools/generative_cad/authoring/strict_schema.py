"""DeepSeek-compatible strict schema compiler.

Converts Pydantic/JSON Schema into the subset accepted by DeepSeek strict
tool calling. DeepSeek strict mode requires every object to have
additionalProperties=false and all properties listed in required.

Key rules:
  - additionalProperties=false on every object.
  - required = all property names on every object.
  - Optional fields become anyOf [<type>, {"type": "null"}].
  - $defs are preserved if present.
  - enum / const are preserved.
  - number minimum/maximum/exclusive* preserved.
  - unsupported keywords (minLength, maxLength, minItems, maxItems) stripped
    with optional x-local-validation markers.
"""

from __future__ import annotations

import copy
from typing import Any

# DeepSeek does not enforce these keywords in strict mode
UNSUPPORTED_KEYWORDS = {
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "patternProperties",
    "unevaluatedProperties",
}

# DeepSeek accepts these numeric constraints
SUPPORTED_NUMERIC = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
}


def to_deepseek_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON Schema dict to DeepSeek strict-mode compatible subset.

    This function is deterministic. It does not weaken semantic validation.
    Constraints unsupported by DeepSeek are stripped with diagnostics stored
    in x-local-validation where appropriate.
    """
    result = copy.deepcopy(schema)
    _transform_object(result)
    return result


def _transform_object(node: dict[str, Any]) -> None:
    """Recursively transform schema objects for DeepSeek strict mode."""
    if not isinstance(node, dict):
        return

    node_type = node.get("type")

    # ── Process $defs ──
    if "$defs" in node:
        for def_schema in node["$defs"].values():
            if isinstance(def_schema, dict):
                _transform_object(def_schema)

    # ── Process anyOf / oneOf / allOf ──
    for comb_key in ("anyOf", "oneOf", "allOf"):
        if comb_key in node:
            for sub in node[comb_key]:
                if isinstance(sub, dict):
                    _transform_object(sub)

    # ── Process items (arrays) ──
    if "items" in node and isinstance(node["items"], dict):
        _transform_object(node["items"])

    # ── Process properties ──
    props = node.get("properties")
    if isinstance(props, dict):
        required_list: list[str] = list(props.keys())

        for prop_name, prop_schema in list(props.items()):
            if not isinstance(prop_schema, dict):
                continue

            # Handle optional fields: convert to anyOf [<type>, null]
            existing_required = node.get("required", [])
            is_required = prop_name in existing_required if isinstance(existing_required, list) else False

            if not is_required:
                # Convert optional to nullable via anyOf
                nullable_schema = _make_nullable(prop_schema)
                props[prop_name] = nullable_schema

            # Recurse
            _transform_object(props[prop_name])

        # DeepSeek strict: all properties must be required
        node["required"] = required_list

        # Strip unsupported keywords from properties
        for prop_schema in props.values():
            if isinstance(prop_schema, dict):
                _strip_unsupported(prop_schema)

    # ── Fix empty objects for DeepSeek strict mode ──
    # DeepSeek requires every object to have non-empty properties AND
    # required must list ALL properties. For dict[str, Any] (no properties),
    # add a dummy placeholder property.
    if isinstance(props, dict):
        if props:
            node["additionalProperties"] = False
            # Ensure required matches ALL properties exactly
            node["required"] = list(props.keys())
        elif node_type == "object" or "properties" in node:
            # Empty properties + type=object: DeepSeek rejects this.
            # Add a minimal placeholder to satisfy the constraint.
            node["properties"] = {"_": {"type": "string"}}
            node["required"] = ["_"]
            node["additionalProperties"] = True
    elif node_type == "object" and not isinstance(props, dict):
        # Object type with no properties at all (dict[str, Any]).
        # Must add properties for DeepSeek.
        node["properties"] = {"_": {"type": "string"}}
        node["required"] = ["_"]
        node["additionalProperties"] = True

    # Strip unsupported keywords at this level
    _strip_unsupported(node)


def _make_nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """Wrap a schema in anyOf [<type>, {"type": "null"}] for optional fields."""
    # If already has anyOf, add null variant
    if "anyOf" in schema:
        has_null = any(
            isinstance(s, dict) and s.get("type") == "null"
            for s in schema["anyOf"]
        )
        if not has_null:
            schema["anyOf"].append({"type": "null"})
        return schema

    # Simple type → wrap in anyOf
    original = {k: v for k, v in schema.items() if k != "description"}

    # DeepSeek rejects {"type": "object"} with no properties.
    # For open dict types (dict[str, Any]): keep type=object with
    # a minimal placeholder property and additionalProperties=true.
    if original.get("type") == "object" and "properties" not in original:
        return {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {"_": {"type": "string"}},
                    "required": ["_"],
                    "additionalProperties": True,
                    "title": original.get("title", ""),
                },
                {"type": "null"},
            ],
        }

    return {
        "anyOf": [
            original,
            {"type": "null"},
        ],
    }


def _strip_unsupported(node: dict[str, Any]) -> None:
    """Remove keywords unsupported by DeepSeek strict mode.

    MinLength/MaxLength/MinItems/MaxItems constraints are moved to
    x-local-validation so the local validator can still enforce them.
    """
    stripped: dict[str, Any] = {}

    for kw in list(node.keys()):
        if kw in UNSUPPORTED_KEYWORDS:
            stripped[kw] = node.pop(kw)

    if stripped:
        existing = node.get("x-local-validation", {})
        if isinstance(existing, dict):
            existing.update(stripped)
        else:
            existing = dict(stripped)
        node["x-local-validation"] = existing


def strict_schema_from_pydantic(model_cls: type) -> dict[str, Any]:
    """Convenience: Pydantic model → DeepSeek strict schema."""
    return to_deepseek_strict_schema(model_cls.model_json_schema())
