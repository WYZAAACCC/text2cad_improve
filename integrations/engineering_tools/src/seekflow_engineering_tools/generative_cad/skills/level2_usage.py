"""Level-2 usage skill generator — builds markdown from BasePackage + Dialect + OperationSpec.

This module replaces the hand-written OP_DESCRIPTIONS in orchestrator.py.
All operation metadata is sourced from OperationSpec fields, not hard-coded
in the orchestrator.
"""

from __future__ import annotations

import hashlib
from typing import Any


def generate_level2_usage_skill(
    *,
    dialect: Any,  # BaseDialect (protocol — avoid hard import to prevent circular deps)
    package_manifest: Any,  # BasePackageManifest
    include_examples: bool = True,
    max_examples: int = 3,
) -> str:
    """Generate a Level-2 usage skill markdown string.

    Information sources (in priority order):
      1. OperationSpec metadata (summary, usage_notes, common_mistakes, llm_param_hints)
      2. params_model Field(description=...) annotations
      3. dialect contract (phase_order, etc.)
      4. package manifest (typical_parts, unsupported_cases, etc.)

    Args:
        dialect: A BaseDialect instance.
        package_manifest: A BasePackageManifest instance.
        include_examples: Include example graphs in the output.
        max_examples: Maximum number of examples to include.

    Returns:
        Markdown string suitable for inclusion in a Level-2 authoring prompt.
    """
    dialect_id = dialect.dialect_id
    contract = dialect.contract()
    phase_order = contract.get("phase_order", getattr(dialect, "phase_order", ()))

    lines: list[str] = []

    # ── Header ──
    lines.append(f"# Dialect Usage Skill: {dialect_id}")
    lines.append("")

    # ── Purpose ──
    lines.append("## Purpose")
    lines.append("")
    paradigm = getattr(package_manifest, "modeling_paradigm", "")
    summary = getattr(package_manifest, "summary", "")
    if summary:
        lines.append(summary)
    lines.append("")
    lines.append(
        f"The `{dialect_id}` dialect is a **grammar** — not a part template. "
        f"It defines a modeling paradigm ({paradigm or 'generic'}) and a set of "
        f"composable operations. Use it to express geometry that fits this paradigm; "
        f"do NOT treat it as a library of pre-made parts."
    )
    lines.append("")

    # ── When to use ──
    lines.append("## When to use")
    lines.append("")
    typical_geo = getattr(package_manifest, "typical_geometry", [])
    typical_parts = getattr(package_manifest, "typical_parts", [])
    if typical_geo:
        for item in typical_geo:
            lines.append(f"- {item}")
    if typical_parts:
        lines.append("")
        lines.append("Common part intents that route here (for routing only — these are NOT op names):")
        for item in typical_parts:
            lines.append(f"- {item}")
    lines.append("")

    # ── When NOT to use ──
    lines.append("## When NOT to use")
    lines.append("")
    unsupported = getattr(package_manifest, "unsupported_cases", [])
    for item in unsupported:
        lines.append(f"- {item}")
    primitive_when = getattr(package_manifest, "primitive_preferred_when", [])
    if primitive_when:
        lines.append("")
        lines.append("Prefer deterministic primitives when:")
        for item in primitive_when:
            lines.append(f"- {item}")
    lines.append("")

    # ── Core graph pattern ──
    lines.append("## Core graph pattern")
    lines.append("")
    lines.append(
        "- One or more components, each with a single `owner_dialect`.\n"
        "- Each component has a `root_node` (the final node in its chain).\n"
        "- Nodes within a component form a DAG via `inputs` → `outputs`.\n"
        "- The first node in a component typically has no inputs (creates geometry).\n"
        "- Subsequent nodes consume and produce `solid`.\n"
        "- Multi-dialect combinations use a `__assembly__` component with `composition` dialect."
    )
    lines.append("")

    # ── Phase order ──
    lines.append("## Phase order")
    lines.append("")
    if phase_order:
        for i, phase in enumerate(phase_order):
            lines.append(f"{i + 1}. `{phase}`")
    else:
        lines.append("(no phase order defined)")
    lines.append("")

    # ── Operations ──
    lines.append("## Operations")
    lines.append("")
    for (op_name, _op_ver), spec in dialect.op_specs().items():
        _append_op_section(lines, spec)
    lines.append("")

    # ── Valid graph skeletons ──
    if include_examples:
        lines.append("## Valid graph skeletons")
        lines.append("")
        lines.append(
            "Refer to the BasePackage examples for complete, validated graph "
            "skeletons. Each example has been verified to pass parse → validation "
            "→ canonicalization."
        )
        lines.append("")

    # ── Anti-patterns ──
    lines.append("## Anti-patterns")
    lines.append("")
    _append_anti_patterns(lines)
    lines.append("")

    # ── Repair hints ──
    lines.append("## Repair hints")
    lines.append("")
    lines.append(
        "- Only patch `/nodes/<id>/params/<field>` or structural fields explicitly flagged by validation.\n"
        "- Do NOT change `/safety`, `/schema_version`, `/selected_dialects`.\n"
        "- Do NOT change `/nodes/<id>/dialect`, `/nodes/<id>/op`, `/nodes/<id>/op_version`.\n"
        "- Do NOT change `/components/<id>/owner_dialect`.\n"
        "- If the same error signature repeats, output `{\"give_up\": true, \"reason\": \"...\"}`.\n"
        "- If repair would require changing forbidden fields, give up."
    )

    return "\n".join(lines)


def _append_op_section(lines: list[str], spec: Any) -> None:
    """Append a per-operation section to the usage skill."""
    op_name = spec.op
    op_version = spec.op_version

    lines.append(f"### `{op_name}` (v{op_version})")
    lines.append("")

    # Summary
    summary = getattr(spec, "summary", None)
    if summary:
        lines.append(f"**Summary:** {summary}")
        lines.append("")

    lines.append(f"- **Dialect:** `{spec.dialect}`")
    lines.append(f"- **Phase:** `{spec.phase}`")
    lines.append(f"- **Input types:** {[t for t in spec.input_types] if spec.input_types else 'none'}")
    lines.append(f"- **Output types:** {[t for t in spec.output_types]}")
    lines.append(f"- **Effects:** {[e for e in spec.effects]}")
    if spec.postconditions:
        lines.append(f"- **Postconditions:** {spec.postconditions}")
    lines.append("")

    # Usage notes
    usage_notes = getattr(spec, "usage_notes", [])
    if usage_notes:
        lines.append("**Usage notes:**")
        for note in usage_notes:
            lines.append(f"- {note}")
        lines.append("")

    # Common mistakes
    common_mistakes = getattr(spec, "common_mistakes", [])
    if common_mistakes:
        lines.append("**Common mistakes:**")
        for m in common_mistakes:
            lines.append(f"- ❌ {m}")
        lines.append("")

    # Params schema summary
    lines.append("**Parameters:**")
    lines.append("")
    try:
        ps = spec.params_model.model_json_schema()
        props = ps.get("properties", {})
        required = ps.get("required", [])
        if props:
            for pname, pinfo in props.items():
                req_mark = " (required)" if pname in required else ""
                ptype = pinfo.get("type", "any")
                desc = pinfo.get("description", "")
                constraints = _extract_constraints(pinfo)
                line = f"- `{pname}`: `{ptype}`{req_mark}"
                if desc:
                    line += f" — {desc}"
                if constraints:
                    line += f" {constraints}"
                lines.append(line)
        else:
            lines.append("(no parameters)")
    except Exception:
        lines.append("(params schema unavailable)")
    lines.append("")

    # LLM param hints
    llm_hints = getattr(spec, "llm_param_hints", {})
    if llm_hints:
        lines.append("**LLM hints:**")
        for pname, hint in llm_hints.items():
            lines.append(f"- `{pname}`: {hint}")
        lines.append("")


def _extract_constraints(pinfo: dict) -> str:
    """Extract human-readable constraints from a JSON Schema property."""
    parts = []
    if "minimum" in pinfo:
        parts.append(f"≥{pinfo['minimum']}")
    if "maximum" in pinfo:
        parts.append(f"≤{pinfo['maximum']}")
    if "exclusiveMinimum" in pinfo:
        parts.append(f">{pinfo['exclusiveMinimum']}")
    if "exclusiveMaximum" in pinfo:
        parts.append(f"<{pinfo['exclusiveMaximum']}")
    if "minLength" in pinfo:
        parts.append(f"min length {pinfo['minLength']}")
    if "maxLength" in pinfo:
        parts.append(f"max length {pinfo['maxLength']}")
    if "minItems" in pinfo:
        parts.append(f"min {pinfo['minItems']} items")
    if "maxItems" in pinfo:
        parts.append(f"max {pinfo['maxItems']} items")
    if "enum" in pinfo:
        parts.append(f"one of: {pinfo['enum']}")
    if parts:
        return "[constraint: " + ", ".join(parts) + "]"
    return ""


def _append_anti_patterns(lines: list[str]) -> None:
    """Append standard anti-patterns shared across all dialects."""
    patterns = [
        "❌ **Part-named ops:** `make_bracket`, `make_flange`, `make_turbine_disk`, etc. Only registered OperationSpec ops are valid.",
        "❌ **Direct CAD code:** CadQuery, SolidWorks COM, NXOpen, APDL, or any Python CAD imports.",
        "❌ **Unknown ops:** Inventing operation names not listed in this skill.",
        "❌ **Cross-dialect direct refs:** Referencing internal nodes from another dialect directly. Use composition component outputs.",
        "❌ **Safety false:** Any safety flag set to `false`. All must be explicitly `true`.",
        "❌ **Missing constraints:** `require_step_file`, `require_metadata_sidecar`, or `require_closed_solid` not explicitly `true`.",
        "❌ **Wrong field names:** Using deprecated field names like `selected_bases`, `base_id`, `feature_graph`.",
        "❌ **Free-form params:** Inventing parameter fields not defined in the OperationSpec params_model.",
    ]
    for p in patterns:
        lines.append(p)


def compute_level2_skill_hash(markdown: str) -> str:
    """Compute a stable hash for a Level-2 usage skill markdown string."""
    return "sha256:" + hashlib.sha256(markdown.encode("utf-8")).hexdigest()
