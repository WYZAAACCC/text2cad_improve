"""Fact Propagation Pass — first real CompilerPass in the middle-end.

Walks the canonical operation graph in topological order and derives
ShapeFacts for each solid-producing node using per-operation fact rules.

Phase 1 coverage:
  - axisymmetric.revolve_profile → radius/bbox/faces
  - axisymmetric.cut_center_bore → propagate + inner_cylindrical face
  - axisymmetric.cut_circular_hole_pattern → hole pattern feasibility
  - axisymmetric.cut_annular_groove → groove feasibility
  - composition.translate_solid → shifted bbox propagation
  - composition.boolean_union → union bbox
  - composition.boolean_cut → conservative copy + cutter warning

Nodes without registered fact rules are silently skipped.
Facts with confidence="unknown" are not errors — they just mean
the compiler couldn't determine the value statically.
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.analysis.fact_rules import (
    get_fact_rule,
)
from seekflow_engineering_tools.generative_cad.analysis.facts import FactStore
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode


class FactPropagationPass:
    """Compiler pass: derive ShapeFacts for all solid-producing nodes.

    Walks nodes in topological order so downstream facts can read upstream
    facts from the FactStore.
    """

    name = "fact_propagation"

    def run(self, module: "CompilerModule") -> "CompilerModule":
        """Run fact propagation on all components in the canonical document."""
        from seekflow_engineering_tools.generative_cad.compiler.module import CompilerModule

        canonical = module.canonical
        if canonical is None:
            module.add_issue(
                stage="fact_propagation",
                code="no_canonical",
                message="No canonical document to analyze.",
                severity="error",
            )
            return module

        store = FactStore()

        # Process each non-assembly component in order
        for component in canonical.components:
            if component.id == "__assembly__":
                continue

            nodes = [
                n for n in canonical.nodes
                if n.component == component.id
            ]

            if not nodes:
                continue

            # Execute in topological order within the component
            ordered = self._topological_sort(nodes)
            for node in ordered:
                try:
                    self._process_node(node, component.id, store, module)
                except Exception as exc:
                    module.add_issue(
                        stage="fact_propagation",
                        code="fact_rule_exception",
                        message=(
                            f"Fact rule for {node.dialect}.{node.op} "
                            f"on node '{node.id}' raised: {exc}"
                        ),
                        severity="error",
                        node_id=node.id,
                        component_id=component.id,
                    )

        # Also process assembly component for composition ops
        assembly = next(
            (c for c in canonical.components if c.id == "__assembly__"), None
        )
        if assembly is not None:
            assembly_nodes = [
                n for n in canonical.nodes
                if n.component == "__assembly__"
            ]
            ordered = self._topological_sort(assembly_nodes)
            for node in ordered:
                try:
                    self._process_node(node, assembly.id, store, module)
                except Exception as exc:
                    module.add_issue(
                        stage="fact_propagation",
                        code="fact_rule_exception",
                        message=(
                            f"Fact rule for {node.dialect}.{node.op} "
                            f"on node '{node.id}' raised: {exc}"
                        ),
                        severity="error",
                        node_id=node.id,
                        component_id=assembly.id,
                    )

        # Store results in the module
        module.facts = store
        return module

    def _process_node(
        self,
        node: CanonicalNode,
        component_id: str,
        store: FactStore,
        module: "CompilerModule",
    ) -> None:
        """Derive facts for a single node and store in FactStore.

        Resolves any DimExpr values in typed_params using upstream facts
        before calling the fact rule. This allows LLMs to use symbolic
        expressions like "outer_radius * 0.6" instead of hardcoded numbers.
        """
        rule = get_fact_rule(node.dialect, node.op)
        if rule is None:
            return  # No rule registered for this op — skip silently

        # ── Phase 2: Resolve DimExpr in typed_params ──
        if node.typed_params:
            try:
                from seekflow_engineering_tools.generative_cad.analysis.expr_eval import (
                    resolve_typed_params_dim_exprs,
                )
                resolved = resolve_typed_params_dim_exprs(node.typed_params, store)
                # Mutate in-place: typed_params is a plain dict, not frozen.
                # Safe to mutate because canonical_graph_hash uses params, not typed_params.
                node.typed_params.clear()
                node.typed_params.update(resolved)
            except Exception as exc:
                module.add_issue(
                    stage="fact_propagation",
                    code="dim_expr_resolution_error",
                    message=f"DimExpr resolution failed on node '{node.id}': {exc}",
                    severity="error",
                    node_id=node.id,
                    component_id=component_id,
                )

        facts = rule(node, component_id, store)

        # Bind facts for each solid output
        for output in node.outputs:
            if output.type == "solid":
                facts.value_id = (
                    f"{output.type}:{node.component}:{node.id}:{output.name}"
                )
                facts.value_type = output.type
                store.bind(node.id, output.name, facts)

        # Emit feasibility errors/warnings from fact notes
        for note in facts.notes:
            if note.startswith("FEASIBILITY ERROR:"):
                module.add_issue(
                    stage="fact_propagation",
                    code="feasibility_error",
                    message=note,
                    severity="error",
                    node_id=node.id,
                    component_id=component_id,
                )
            elif note.startswith("FEASIBILITY WARNING:") or note.startswith("WARNING:"):
                module.add_issue(
                    stage="fact_propagation",
                    code="feasibility_warning",
                    message=note,
                    severity="warning",
                    node_id=node.id,
                    component_id=component_id,
                )

    @staticmethod
    def _topological_sort(nodes: list[CanonicalNode]) -> list[CanonicalNode]:
        """Topological sort nodes by input dependencies.

        Falls back to input order if the graph has cycles
        (which shouldn't happen — validation catches cycles).
        """
        node_map = {n.id: n for n in nodes}

        # Build in-degree map (count upstream node dependencies)
        in_degree: dict[str, int] = {}
        for n in nodes:
            deg = 0
            for inp in n.inputs:
                if inp.producer_node and inp.producer_node in node_map:
                    deg += 1
            in_degree[n.id] = deg

        queue = [n for n in nodes if in_degree.get(n.id, 0) == 0]
        result: list[CanonicalNode] = []

        while queue:
            # Stable sort by id for determinism
            queue.sort(key=lambda n: n.id)
            n = queue.pop(0)
            result.append(n)

            for other in nodes:
                for inp in other.inputs:
                    if inp.producer_node == n.id:
                        in_degree[other.id] -= 1
                        if in_degree[other.id] == 0 and other not in result and other not in queue:
                            queue.append(other)

        # If some nodes not scheduled (shouldn't happen post-validation),
        # append them in original order
        for n in nodes:
            if n not in result:
                result.append(n)

        return result
