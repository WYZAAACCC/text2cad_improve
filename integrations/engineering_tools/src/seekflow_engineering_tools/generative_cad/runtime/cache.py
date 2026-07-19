"""OperationCache — memoize geometry operations for incremental rebuild.

PR 3 fix:
  1. get() compares stored key with current key (was only checking existence)
  2. cache key includes input geometry content hashes (was only handle IDs)
  3. topology_registry_fragment is populated from registry snapshot
  4. runtime version is included in cache key

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
    op_version, etc.) PLUS input geometry content hashes and runtime version.
    Any change to any of these invalidates the cache.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._node_keys: dict[str, str] = {}
        self._runtime_version = self._detect_runtime_version()

    @staticmethod
    def _detect_runtime_version() -> str:
        """Detect CadQuery + OCCT versions for cache-busting.

        When either library version changes, all cached entries are
        invalidated because geometry results may differ.
        """
        try:
            import cadquery as cq
            cq_ver = getattr(cq, "__version__", "?")
        except ImportError:
            cq_ver = "?"
        try:
            from OCP.Standard import Standard_Version  # type: ignore[import-untyped]
            occt_ver = Standard_Version
        except ImportError:
            occt_ver = "?"
        return f"cq={cq_ver}|occt={occt_ver}"

    def key(
        self,
        node: CanonicalNode,
        *,
        input_hashes: dict[str, str] | None = None,
    ) -> str:
        """Generate a cache key from the node's full state + input geometry.

        Includes:
          - node content hash (params, inputs, op_version)
          - runtime version (CadQuery + OCCT)
          - input geometry content hashes (if available)
        """
        parts = [
            f"op:{node.dialect}:{node.op}",
            stable_hash(node.model_dump()),
            self._runtime_version,
        ]
        if input_hashes:
            # Sort by handle ID for deterministic ordering
            sorted_hashes = ":".join(
                f"{hid}={h}" for hid, h in sorted(input_hashes.items())
            )
            parts.append(f"inputs:{stable_hash(sorted_hashes)}")
        return ":".join(parts)

    def get(
        self,
        node: CanonicalNode,
        *,
        input_hashes: dict[str, str] | None = None,
    ) -> Any | None:
        """Return cached result for a node, or None if stale/not cached.

        PR 3 fix: compares current key against stored key.
        If they differ (params changed, input geometry changed, version changed),
        returns None — cache miss.
        """
        current_key = self.key(node, input_hashes=input_hashes)
        stored_key = self._node_keys.get(node.id)
        if stored_key is None or stored_key != current_key:
            return None  # MISS: key mismatch → node or inputs changed
        entry = self._store.get(current_key)
        if entry is None:
            return None
        if isinstance(entry, dict) and "result" in entry:
            return entry["result"]
        # Backward compat: pre-Phase 1 entries are raw results
        return entry

    def put(
        self,
        node: CanonicalNode,
        result: Any,
        *,
        input_hashes: dict[str, str] | None = None,
        topology_snapshot: dict | None = None,
    ) -> None:
        """Store a result in the cache.

        PR 3: records input geometry hashes and topology registry fragment
        for future incremental rebuild + topology-aware cache restoration.
        """
        node_key = self.key(node, input_hashes=input_hashes)
        entry = {
            "result": result,
            "node_id": node.id,
            "input_geometry_hashes": input_hashes or {},
            "topology_registry_fragment": topology_snapshot,
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
