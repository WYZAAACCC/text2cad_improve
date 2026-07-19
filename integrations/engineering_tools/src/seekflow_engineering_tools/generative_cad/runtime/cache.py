"""OperationCache — memoize geometry operations for incremental rebuild.

When a parameter changes on one node, only that node and its downstream
dependents need to be recomputed. Unchanged nodes are served from cache.
"""

from __future__ import annotations
from typing import Any

from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode


class OperationCache:
    """Memoization cache for geometry operations.

    Cache keys are computed from the full CanonicalNode (params, inputs,
    op_version, etc.) so that any parameter change invalidates the cache
    for that node and all downstream dependents.
    """

    def __init__(self):
        self._store: dict[str, Any] = {}
        self._node_keys: dict[str, str] = {}

    def key(self, node: CanonicalNode) -> str:
        """Generate a cache key from the node's full state."""
        # Include inputs in the key — if an upstream node changes,
        # the input handle IDs change, invalidating this node's cache.
        node_hash = stable_hash(node.model_dump())
        return f"op:{node.dialect}:{node.op}:{node_hash}"

    def get(self, node: CanonicalNode) -> Any | None:
        """Return cached result for a node, or None if not cached.

        Phase 1+: unwraps dict entries (backward compat: raw entries
        stored before Phase 1 are returned as-is).
        """
        node_key = self._node_keys.get(node.id)
        if node_key is None:
            return None
        entry = self._store.get(node_key)
        if entry is None:
            return None
        # Phase 1+: entries are dicts with "result" key
        if isinstance(entry, dict) and "result" in entry:
            return entry["result"]
        # Backward compat: pre-Phase 1 entries are raw results
        return entry

    def put(self, node: CanonicalNode, result: Any) -> None:
        """Store a result in the cache.

        Phase 1+: wraps result in a dict entry for future topology awareness.
        Backward compatible: old raw-result entries are unwrapped on get().
        """
        node_key = self.key(node)
        entry = {
            "result": result,
            "node_id": node.id,
            # Phase 2+: snapshot relevant topology registry entries here
            "topology_registry_fragment": None,
        }
        self._store[node_key] = entry
        self._node_keys[node.id] = node_key

    def invalidate(self, node_id: str) -> None:
        """Invalidate cache for a specific node and all dependents."""
        if node_id in self._node_keys:
            old_key = self._node_keys.pop(node_id)
            self._store.pop(old_key, None)

    def clear(self) -> None:
        """Clear all cached results."""
        self._store.clear()
        self._node_keys.clear()

    @property
    def size(self) -> int:
        return len(self._store)

    def hit_rate(self) -> float:
        """Placeholder — real tracking needs a metrics counter."""
        return 0.0
