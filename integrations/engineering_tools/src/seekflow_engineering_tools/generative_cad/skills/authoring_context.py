"""Compact authoring context packer for Level-2 LLM prompts.

Packs the essential context (manifests, contracts, usage skills) into a
form suitable for inclusion in the LLM system prompt, respecting token
budgets and truncation limits.
"""

from __future__ import annotations

from typing import Any


def pack_authoring_context(
    *,
    package_manifests: dict[str, Any],
    usage_skills: dict[str, str],
    max_manifest_chars: int = 3000,
    max_skill_chars: int = 8000,
) -> str:
    """Pack BasePackage context into a compact string for the LLM prompt.

    Args:
        package_manifests: Dict of dialect_id → BasePackageManifest.
        usage_skills: Dict of dialect_id → Level-2 usage skill markdown.
        max_manifest_chars: Max chars for the manifest summary section.
        max_skill_chars: Max chars per usage skill (truncates with note).

    Returns:
        A single string suitable for appending to the system or user message.
    """
    parts: list[str] = []

    # ── Manifest summary ──
    parts.append("## Selected BasePackage Manifests")
    parts.append("")
    for did, manifest in package_manifests.items():
        if hasattr(manifest, "model_dump"):
            m = manifest.model_dump()
        else:
            m = manifest
        parts.append(f"### {did}")
        parts.append(f"- **Title:** {m.get('title', did)}")
        parts.append(f"- **Paradigm:** {m.get('modeling_paradigm', 'unknown')}")
        parts.append(f"- **Typical geometry:** {', '.join(m.get('typical_geometry', []))}")
        parts.append(f"- **Typical parts (routing only):** {', '.join(m.get('typical_parts', []))}")
        unsupported = m.get("unsupported_cases", [])
        if unsupported:
            parts.append(f"- **Unsupported:** {', '.join(unsupported)}")
        parts.append("")

    manifest_text = "\n".join(parts)
    if len(manifest_text) > max_manifest_chars:
        manifest_text = manifest_text[:max_manifest_chars] + "\n\n[... manifest truncated ...]"

    # ── Usage skills ──
    skills_parts: list[str] = []
    skills_parts.append("## Dialect Usage Skills")
    skills_parts.append("")
    for did, skill_md in usage_skills.items():
        truncated = skill_md
        if len(truncated) > max_skill_chars:
            truncated = truncated[:max_skill_chars] + "\n\n[... usage skill truncated ...]"
        skills_parts.append(truncated)
        skills_parts.append("")

    skills_text = "\n".join(skills_parts)

    return manifest_text + "\n\n" + skills_text


def pack_compact_contracts(
    contracts: dict[str, dict],
    max_chars: int = 4000,
) -> str:
    """Pack dialect contracts into a compact string.

    Only includes essential fields: phase_order and operation summaries.
    """
    lines: list[str] = []
    lines.append("## Dialect Contracts (compact)")
    lines.append("")
    for did, contract in contracts.items():
        lines.append(f"### {did}")
        phases = contract.get("phase_order", [])
        if phases:
            lines.append(f"Phase order: {' → '.join(phases)}")
        allowed_ops = contract.get("allowed_ops", {})
        if allowed_ops:
            for op_name, op_info in allowed_ops.items():
                phase = op_info.get("phase", "?")
                desc = op_info.get("description", "")[:120]
                lines.append(f"- `{op_name}` [{phase}]: {desc}")
        lines.append("")

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n\n[... contracts truncated ...]"
    return result
