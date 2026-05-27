from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PrimitiveGraphNode:
    primitive_name: str
    feature_id: str
    parameters: dict
    operation: str = "new_body"
    dependencies: list[str] = field(default_factory=list)


@dataclass
class PrimitiveGraph:
    nodes: list[PrimitiveGraphNode] = field(default_factory=list)

    def sorted_nodes(self) -> list[PrimitiveGraphNode]:
        visited: set[str] = set()
        order: list[PrimitiveGraphNode] = []
        name_to_node = {n.feature_id: n for n in self.nodes}

        def visit(nid: str):
            if nid in visited:
                return
            visited.add(nid)
            node = name_to_node.get(nid)
            if node:
                for dep in node.dependencies:
                    if dep in name_to_node:
                        visit(dep)
                order.append(node)

        for n in self.nodes:
            visit(n.feature_id)

        return order
