"""Tool schema compiler — builds per-op JSON schemas from OperationSpec metadata.

Replaces the hard-coded OP_DESCRIPTIONS in orchestrator.build_level2_tool().
All operation metadata is sourced from OperationSpec fields and params_model
Field(description=...) annotations — not from a hand-written dictionary.

Key rules:
  1. Start from RawGcadDocument.model_json_schema().
  2. selected_dialects enum from registry.list().
  3. dialect version enum from dialect.version, NOT hard-coded "0.2.0".
  4. node anyOf variants from OperationSpec.
  5. node.op_version const = spec.op_version, NOT hard-coded "1.0.0".
  6. params schema from spec.params_model.model_json_schema().
  7. description from spec.summary / usage_notes / params_model field descriptions.
  8. outputs prefixItems from spec.output_types and optional output name policy.
  9. No Chinese op descriptions written in the compiler.
"""

from __future__ import annotations

import copy
from typing import Any


# ── Output name policy ────────────────────────────────────────────────────────

_OUTPUT_NAME_POLICY: dict[str, str] = {
    "solid": "body",
    "frame": "outer_frame",
    "profile": "profile",
    "sketch": "sketch",
    "solid_array": "bodies",
    "plane": "plane",
    "point": "point",
    "curve": "curve",
    "face_set": "faces",
    "edge_set": "edges",
    "component_ref": "component",
}


def _output_name_for_type(vtype: str) -> str:
    """Return the canonical output name for a given ValueType."""
    return _OUTPUT_NAME_POLICY.get(vtype, vtype)


# ── Schema compiler ───────────────────────────────────────────────────────────


def compile_level2_tool_schema(
    *,
    selected_dialects: list[str] | None = None,
    registry: Any = None,  # DialectRegistry
    base_package_registry: Any = None,  # BasePackageRegistry
    raw_schema: dict | None = None,
) -> dict:
    """Compile a Level-2 function-calling tool schema from OperationSpec metadata.

    Args:
        selected_dialects: Optional override for which dialects to include.
            If None, includes all dialects in the registry.
        registry: A DialectRegistry instance.
        base_package_registry: A BasePackageRegistry instance (for descriptions).
        raw_schema: Optional pre-computed RawGcadDocument JSON schema.
            If None, computed fresh.

    Returns:
        A JSON Schema dict (draft-07) suitable for use as the ``parameters``
        field of an OpenAI function-calling tool definition.
    """
    if registry is None:
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        registry = default_registry()

    from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument

    schema = copy.deepcopy(raw_schema or RawGcadDocument.model_json_schema())
    defs = schema.setdefault("$defs", {})
    valid_dialects = selected_dialects or registry.list_ids()

    # ── 1. Constrain top-level fixed-value fields ──
    _constrain_top_level(schema)

    # ── 2. Constrain selected_dialects enum from actual registry ──
    _constrain_selected_dialects(defs, valid_dialects, registry)

    # ── 3. Build per-operation node variants ──
    op_variants = _build_op_variants(valid_dialects, registry, base_package_registry, defs)

    # ── 4. Wire node variants into the nodes array ──
    _wire_node_variants(schema, op_variants)

    return schema


def _constrain_top_level(schema: dict) -> None:
    """Constrain top-level fields to their only legal values."""
    top_props = schema.get("properties", {})
    if "schema_version" in top_props:
        top_props["schema_version"]["const"] = "g_cad_core_v0.2"
    if "units" in top_props:
        top_props["units"]["const"] = "mm"
    if "trust_level" in top_props:
        top_props["trust_level"]["enum"] = ["reference_geometry", "concept_geometry"]


def _constrain_selected_dialects(
    defs: dict,
    valid_dialects: list[str],
    registry: Any,
) -> None:
    """Constrain selected_dialects and component owner_dialect enums."""
    # Build per-dialect version map
    dialect_versions: dict[str, str] = {}
    for dn in valid_dialects:
        d = registry.get(dn)
        if d is not None:
            dialect_versions[dn] = d.version

    for _def_name, def_schema in defs.items():
        props = def_schema.get("properties", {})
        # RawSelectedDialect shape: {dialect, version}
        if set(props.keys()) == {"dialect", "version"}:
            props["dialect"]["enum"] = valid_dialects
            # Use actual dialect versions, not hard-coded "0.2.0"
            versions = sorted(set(dialect_versions.values()))
            props["version"]["enum"] = versions if versions else ["0.2.0"]
        # RawComponent shape: {id, owner_dialect, root_node, ...}
        if "owner_dialect" in props and "root_node" in props and "kind_hint" in props:
            props["owner_dialect"]["enum"] = valid_dialects + ["composition"]


def _build_op_variants(
    valid_dialects: list[str],
    registry: Any,
    bp_reg: Any,
    defs: dict,
) -> list[dict]:
    """Build per-operation node schema variants from OperationSpec."""
    variants: list[dict] = []

    for dn in valid_dialects:
        d = registry.get(dn)
        if d is None:
            continue
        for (_op_name, _op_ver), spec in d.op_specs().items():
            variant = _build_single_op_variant(dn, spec, defs)
            variants.append(variant)

    return variants


def _build_single_op_variant(
    dialect_id: str,
    spec: Any,  # OperationSpec
    defs: dict,
) -> dict:
    """Build a single operation variant schema."""
    op_name = spec.op

    # ── Build outputs with exact names and types ──
    outputs = []
    for otype in spec.output_types:
        outputs.append({
            "name": _output_name_for_type(otype),
            "type": otype,
        })

    # ── Build per-op params schema (with field descriptions) ──
    params_schema = copy.deepcopy(spec.params_model.model_json_schema())
    ref_name = f"{dialect_id}__{op_name}_params"
    params_schema["title"] = ref_name

    # Inject descriptions from params_model field definitions
    _inject_param_descriptions(params_schema, spec)

    defs[ref_name] = params_schema

    # ── Build the description from OperationSpec metadata ──
    description = _build_op_description(spec)

    # ── Build variant ──
    variant: dict = {
        "type": "object",
        "title": f"{dialect_id}.{op_name}",
        "description": description,
        "properties": {
            "id": {
                "type": "string",
                "description": "Unique node identifier, e.g. n1, n_body, n_cut",
            },
            "component": {
                "type": "string",
                "description": "Owning component ID",
            },
            "dialect": {"const": dialect_id},
            "op": {"const": op_name},
            "op_version": {"const": spec.op_version},  # ← from OperationSpec, NOT hard-coded
            "phase": {"const": spec.phase},
            "inputs": {
                "type": "array",
                "description": (
                    f"Input references (exactly {len(spec.input_types)}). "
                    f"Each ref must have 'node' (producer id) and 'output' (output name)."
                ),
                "minItems": len(spec.input_types),
                "maxItems": len(spec.input_types),
                "items": {
                    "type": "object",
                    "properties": {
                        "node": {
                            "type": "string",
                            "description": "Producer node id",
                        },
                        "output": {
                            "type": "string",
                            "description": "Output name, usually 'body'",
                        },
                    },
                    "required": ["node", "output"],
                    "additionalProperties": False,
                },
            },
            "outputs": _build_outputs_schema(outputs),
            "params": {"$ref": f"#/$defs/{ref_name}"},
            "required": {
                "const": True,
                "description": "Whether this node is required",
            },
            "degradation_policy": {
                "const": "fail",
                "description": "Degradation policy. 'fail' = fail on error.",
            },
        },
        "required": [
            "id", "component", "dialect", "op", "op_version",
            "phase", "inputs", "outputs", "params",
            "required", "degradation_policy",
        ],
        "additionalProperties": False,
    }

    return variant


def _build_outputs_schema(outputs: list[dict]) -> dict:
    """Build the outputs array schema with exact prefixItems."""
    if not outputs:
        return {"type": "array", "maxItems": 0}
    return {
        "type": "array",
        "description": f"Node outputs (exactly {len(outputs)})",
        "minItems": len(outputs),
        "maxItems": len(outputs),
        "prefixItems": [{"const": o} for o in outputs],
    }


def _build_op_description(spec: Any) -> str:
    """Build an op description from OperationSpec metadata only.

    Priority order:
      1. spec.summary
      2. spec.usage_notes (first note)
      3. params_model field descriptions (abbreviated)
      4. Fallback generic description
    """
    parts: list[str] = []

    # Summary (primary)
    summary = getattr(spec, "summary", None)
    if summary:
        parts.append(summary)

    # Usage notes
    usage_notes = getattr(spec, "usage_notes", [])
    if usage_notes and not summary:
        parts.append(usage_notes[0][:200])

    # Effects
    effects = getattr(spec, "effects", [])
    if effects:
        parts.append(f"Effects: {', '.join(effects)}")

    # Postconditions
    postconditions = getattr(spec, "postconditions", [])
    if postconditions:
        parts.append(f"Postconditions: {', '.join(postconditions)}")

    if parts:
        return ". ".join(parts)

    # Fallback
    return (
        f"{spec.dialect}.{spec.op} (v{spec.op_version}, phase={spec.phase}). "
        f"Inputs: {[t for t in spec.input_types]}. "
        f"Outputs: {[t for t in spec.output_types]}."
    )


def _inject_param_descriptions(params_schema: dict, spec: Any) -> None:
    """Inject parameter descriptions from params_model Field annotations.

    Also merges llm_param_hints from OperationSpec if available.
    """
    ps_props = params_schema.get("properties", {})
    llm_hints = getattr(spec, "llm_param_hints", {}) or {}

    for fname, finfo in ps_props.items():
        # Use existing description if present
        if finfo.get("description"):
            continue

        # Try to get description from the Pydantic model field
        try:
            field = spec.params_model.model_fields.get(fname)
            if field and field.description:
                finfo["description"] = field.description
        except Exception:
            pass

        # Overlay LLM-specific hints
        if fname in llm_hints:
            existing = finfo.get("description", "")
            finfo["description"] = (
                f"{existing} {llm_hints[fname]}".strip()
                if existing
                else llm_hints[fname]
            )


def _wire_node_variants(schema: dict, op_variants: list[dict]) -> None:
    """Replace nodes.items with the per-operation discriminated union."""
    # Add multi-component guidance
    comp_prop = schema.get("properties", {}).get("components", {})
    if comp_prop:
        comp_prop["description"] = (
            "Component list. Single-part requests need 1 component. "
            "Multi-part assemblies need 1 component per independent part "
            "plus 1 __assembly__ component with owner_dialect='composition'. "
            "Non-assembly components can only contain nodes from their owner_dialect."
        )

    nodes_prop = schema.get("properties", {}).get("nodes", {})
    if nodes_prop:
        nodes_prop["description"] = (
            "Operation node list. Each node must match exactly one of the "
            "operation schemas below. For multi-part assemblies: 1) create "
            "nodes for each independent part (in its component), 2) create "
            "composition nodes in __assembly__ to combine them via boolean ops. "
            "Composition nodes reference other component outputs via inputs."
        )
        nodes_prop["items"] = {"anyOf": op_variants}


# ── Thin wrapper compatible with existing orchestrator API ────────────────────


def build_level2_tool_from_compiler(
    contracts: dict[str, dict] | None = None,
    *,
    selected_dialects: list[str] | None = None,
) -> dict:
    """Build a Level-2 function-calling tool using the schema compiler.

    This is a drop-in replacement for the old build_level2_tool() that
    removes all hard-coded OP_DESCRIPTIONS and version strings.

    Args:
        contracts: Ignored (kept for API compat). Contracts are sourced
            from the registry inside the compiler.
        selected_dialects: Optional override list of dialect IDs.

    Returns:
        An OpenAI function-calling tool dict.
    """
    schema = compile_level2_tool_schema(selected_dialects=selected_dialects)

    from seekflow_engineering_tools.generative_cad.dialects.registry import list_dialects
    valid_dialects = selected_dialects or list_dialects()

    return {
        "type": "function",
        "function": {
            "name": "generate_raw_gcad_document",
            "description": (
                "Generate a RawGcadDocument JSON for the G-CAD Core IR. "
                "Each node in the 'nodes' array must match one of the allowed "
                "operation schemas exactly. Available dialects: "
                + ", ".join(valid_dialects) + "."
            ),
            "parameters": schema,
        },
    }
