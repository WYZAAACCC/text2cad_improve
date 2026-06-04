"""Root terminal validator — ensures root_node points to the true terminal solid.

Prevents g14-class bugs where root_node references an intermediate solid
that is later consumed by holes/slots/patterns, causing those downstream
features to be silently absent from the final component output.

Reference: llm_skill_base21.md §5.1, AUDIT P0-4 (fixed: uses ValidationIssue)
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.validation.reports import (
    ValidationIssue,
    ValidationReport,
)


def validate_root_terminal(subject) -> ValidationReport:
    """Validate that each component's root_node is a terminal solid.

    A "terminal solid" is a solid-producing node whose output is NOT consumed
    as input by any other node within the same component. The root_node must
    be one of these terminal solids, otherwise downstream features (holes,
    slots, patterns, fillets) are silently lost.

    Applies to: RawGcadDocument (dict) or CanonicalGcadDocument.
    """
    issues: list[ValidationIssue] = []
    stage = "structure"

    # Handle both dict (raw) and Pydantic model (canonical)
    components = subject.get("components", []) if isinstance(subject, dict) else getattr(subject, "components", [])
    nodes = subject.get("nodes", []) if isinstance(subject, dict) else getattr(subject, "nodes", [])

    # Build lookup: component_id → nodes
    nodes_by_component: dict[str, list] = {}
    for n in nodes:
        cid = n["component"] if isinstance(n, dict) else n.component
        nodes_by_component.setdefault(cid, []).append(n)

    for comp in components:
        cid = comp["id"] if isinstance(comp, dict) else comp.id
        if cid == "__assembly__":
            continue

        comp_nodes = nodes_by_component.get(cid, [])
        if not comp_nodes:
            continue

        # Collect solid-producing node IDs
        solid_producers: list[str] = []
        for n in comp_nodes:
            outputs = n.get("outputs", []) if isinstance(n, dict) else n.outputs
            nid = n["id"] if isinstance(n, dict) else n.id
            for o in outputs:
                otype = o.get("type", "") if isinstance(o, dict) else o.type
                if otype == "solid":
                    solid_producers.append(nid)
                    break

        if not solid_producers:
            continue

        # Collect consumed node IDs (appear as input to another node)
        consumed: set[str] = set()
        for n in comp_nodes:
            inputs = n.get("inputs", []) if isinstance(n, dict) else n.inputs
            for inp in inputs:
                producer = inp.get("node") if isinstance(inp, dict) else getattr(inp, "producer_node", None)
                if producer:
                    consumed.add(producer)

        # Terminal solids = solid producers not consumed by any downstream node
        terminal_solids = [nid for nid in solid_producers if nid not in consumed]

        root = comp.get("root_node") if isinstance(comp, dict) else comp.root_node
        if root and terminal_solids and root not in terminal_solids:
            issues.append(ValidationIssue(
                stage=stage,
                code="ROOT_NOT_TERMINAL_SOLID",
                message=(
                    f"Component '{cid}' root_node='{root}' is not a terminal solid. "
                    f"It is consumed by downstream operations — those features will "
                    f"be silently absent from the final output. "
                    f"Terminal candidate(s): {terminal_solids}. "
                    f"Fix: set root_node to the LAST solid-producing node that "
                    f"represents the completed component."
                ),
                severity="error",
                component_id=cid,
            ))

    return ValidationReport(
        ok=not any(i.severity == "error" for i in issues),
        stage=stage,
        issues=issues,
    )
