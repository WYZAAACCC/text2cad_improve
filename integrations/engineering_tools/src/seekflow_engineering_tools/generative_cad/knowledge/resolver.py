"""Knowledge Resolver + Compiler — load selected packs and compile prompt content."""
from __future__ import annotations

from dataclasses import dataclass, field

from seekflow_engineering_tools.generative_cad.knowledge.registry import KnowledgeRegistry
from seekflow_engineering_tools.generative_cad.knowledge.schemas import KnowledgePack, KnowledgePackManifest


@dataclass
class ResolvedKnowledge:
    """Fully resolved and validated knowledge for a single generation request."""
    packs: list[KnowledgePack] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


class KnowledgeResolver:
    """Resolve knowledge pack selections into loaded, validated packs."""

    def __init__(self, registry: KnowledgeRegistry):
        self._registry = registry

    def resolve(self, selections: list[dict]) -> ResolvedKnowledge:
        """Validate and load the selected knowledge packs.

        Each selection dict must contain ``skill_id`` and optionally ``skill_version``.
        """
        errors = self._registry.validate_selections(selections)
        if errors:
            return ResolvedKnowledge(errors=errors)

        packs: list[KnowledgePack] = []
        for sel in selections:
            sid = sel.get("skill_id", "")
            ver = sel.get("skill_version")
            pack = self._registry.get(sid, ver)
            if pack:
                packs.append(pack)

        return ResolvedKnowledge(packs=packs)


def compile_l1_summary(packs: list[KnowledgePack]) -> list[dict]:
    """Produce a compact summary for L1 routing prompt.

    L1 only needs to know what's available — not full rules.
    """
    summaries = []
    for p in packs:
        m = p.manifest
        summaries.append({
            "skill_id": m.skill_id,
            "version": m.version,
            "title": m.title,
            "object_types": m.object_types,
            "feature_types": m.feature_types,
            "trigger_terms": m.trigger_terms[:5],  # top 5 for token budget
            "required_dialects": m.required_dialects,
            "status": m.status,
        })
    return summaries


# ── Prompt compilation ────────────────────────────────────────────────────

# Priority weights for prompt sections. Higher = included first when budget is tight.
SECTION_PRIORITY: dict[str, int] = {
    "hard_rules": 100,
    "variant_conflicts": 98,
    "topology": 95,
    "parameter_semantics": 92,
    "operation_mapping": 88,
    "self_checks": 85,
    "anti_examples": 80,
    "construction_strategy": 75,
    "correct_examples": 60,
    "background": 20,
}

# Sections that must never be truncated
CRITICAL_SECTIONS = {
    "hard_rules",
    "variant_conflicts",
    "parameter_semantics",
    "self_checks",
    "topology",
}


def compile_l2_knowledge(resolved: ResolvedKnowledge, char_budget: int = 3000) -> str:
    """Compile loaded knowledge packs into an L2 prompt section.

    Rules are ordered by severity: hard → strong_preference → heuristic → informational.
    Within each severity, rules are ordered by SECTION_PRIORITY.
    Critical sections are never truncated.
    """
    if not resolved.packs:
        return ""

    sections: list[tuple[int, str, str]] = []  # (priority, heading, content)

    for pack in resolved.packs:
        prefix = f"[{pack.manifest.skill_id}@{pack.manifest.version}]"

        # ── hard rules ──
        hard_lines: list[str] = []
        for r in pack.topology_rules:
            if r.severity == "hard":
                hard_lines.append(f"  - {r.statement}")
        for r in pack.parameter_rules:
            if r.severity == "hard":
                hard_lines.append(f"  - {r.statement}")
        for r in pack.self_check_rules:
            if r.severity == "hard":
                hard_lines.append(f"  - {r.statement}")
        if hard_lines:
            sections.append((
                SECTION_PRIORITY.get("hard_rules", 100),
                f"Hard Engineering Rules {prefix}",
                "\n".join(hard_lines),
            ))

        # ── parameter semantics ──
        param_lines: list[str] = []
        for r in pack.parameter_rules:
            if r.severity != "hard":
                param_lines.append(f"  - {r.statement}")
        if param_lines:
            sections.append((
                SECTION_PRIORITY.get("parameter_semantics", 92),
                f"Parameter Guidance {prefix}",
                "\n".join(param_lines),
            ))

        # ── topology ──
        topo_lines: list[str] = []
        for r in pack.topology_rules:
            if r.severity != "hard":
                topo_lines.append(f"  - {r.statement}")
        if topo_lines:
            sections.append((
                SECTION_PRIORITY.get("topology", 95),
                f"Topology Guidance {prefix}",
                "\n".join(topo_lines),
            ))

        # ── construction strategy ──
        if pack.construction_strategy.strip():
            sections.append((
                SECTION_PRIORITY.get("construction_strategy", 75),
                f"Construction Strategy {prefix}",
                pack.construction_strategy,
            ))

        # ── self-checks ──
        check_lines: list[str] = []
        for r in pack.self_check_rules:
            if r.severity != "hard":
                check_lines.append(f"  - {r.statement}")
        if check_lines:
            sections.append((
                SECTION_PRIORITY.get("self_checks", 85),
                f"Self-Checks {prefix}",
                "\n".join(check_lines),
            ))

        # ── known conflicts ──
        if pack.known_conflicts:
            conflict_text = "\n".join(
                f"  - {c.get('conflict_id', '?')}: {c.get('resolution_policy', '')}"
                for c in pack.known_conflicts
            )
            sections.append((
                SECTION_PRIORITY.get("variant_conflicts", 98),
                f"Known Variant Conflicts {prefix}",
                conflict_text,
            ))

    # Sort by priority descending
    sections.sort(key=lambda x: -x[0])

    # Assemble with token budget
    parts: list[str] = []
    parts.append("## DOMAIN KNOWLEDGE (from versioned Knowledge Packs)\n")
    current_chars = len(parts[0])

    for priority, heading, content in sections:
        block = f"### {heading}\n{content}\n"
        block_chars = len(block)

        # Critical sections always included
        is_critical = any(cs in heading.lower().replace(" ", "_") for cs in CRITICAL_SECTIONS)
        # Also detect hard rules from the heading
        is_hard = "hard engineering rules" in heading.lower()

        if is_critical or is_hard or (current_chars + block_chars) <= char_budget:
            parts.append(block)
            current_chars += block_chars
        else:
            parts.append(f"### {heading}\n(content truncated — char budget exceeded)\n")
            break

    return "".join(parts)
