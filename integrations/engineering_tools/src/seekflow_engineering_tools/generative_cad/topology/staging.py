"""Atomic staging for geometry + topology + cache — §2.13 of the supplementary spec.

Provides:
  - StagedObjectStore: temporary object staging before permanent commit
  - BuildCommitBundle: atomic commit bundle for all staged state

The core problem: handlers currently write geometry to ObjectStore before applying
topology deltas. If the delta fails, the geometry is already persisted — leaving
a permanent handle with no topology record. The BuildCommitBundle solves this
by staging ALL state (objects, registry entities, node bindings, events, cache)
and only publishing when validation passes.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §2.13
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seekflow_engineering_tools.generative_cad.runtime.handles import RuntimeHandle


# ═══════════════════════════════════════════════════════════════════════════════
# StagedObjectStore — temporary staging area (§2.13)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class StagedObjectStore:
    """Temporary staging area for objects before atomic commit.

    Handlers stage geometry objects here instead of writing directly to
    RuntimeObjectStore. When BuildCommitBundle validates, all staged objects
    are atomically published. On rollback, staged objects are discarded.

    This eliminates the "geometry persisted but topology failed" split-brain.
    """

    _objects: dict[str, Any] = field(default_factory=dict)
    _handles: dict[str, RuntimeHandle] = field(default_factory=dict)
    _revisions: dict[str, int] = field(default_factory=dict)

    # ── Staging ──

    def stage(self, handle: RuntimeHandle, obj: Any) -> RuntimeHandle:
        """Stage an object for later commit.

        Does NOT write to the real ObjectStore. The object is held in the
        staging area until commit_to() is called.
        """
        hid = handle.id
        self._handles[hid] = handle
        self._objects[hid] = obj
        self._revisions[hid] = 1
        return handle

    def stage_replace(self, handle: RuntimeHandle, obj: Any) -> RuntimeHandle:
        """Stage a replacement for an already-staged object.

        Bumps the staged revision counter for staleness detection.
        """
        hid = handle.id
        if hid not in self._objects:
            raise KeyError(
                f"Cannot stage-replace unknown handle: {hid}. "
                f"Use stage() for new objects."
            )
        self._handles[hid] = handle
        self._objects[hid] = obj
        self._revisions[hid] = self._revisions.get(hid, 0) + 1
        return handle

    def get_staged(self, handle_id: str) -> Any:
        """Get a staged object by handle ID."""
        if handle_id not in self._objects:
            raise KeyError(f"Staged object not found: {handle_id}")
        return self._objects[handle_id]

    def contains(self, handle_id: str) -> bool:
        """Check if a handle ID is staged."""
        return handle_id in self._objects

    # ── Commit / Rollback ──

    def commit_to(self, store: Any) -> list[str]:
        """Atomically publish all staged objects to a real ObjectStore.

        Args:
            store: RuntimeObjectStore instance to commit into.

        Returns:
            List of handle IDs that were committed (empty if nothing staged).
        """
        committed: list[str] = []
        for hid, obj in self._objects.items():
            handle = self._handles[hid]
            try:
                # Use replace for existing, put for new
                try:
                    store.get(handle)
                    store.replace(handle, obj)
                except KeyError:
                    store.put(handle, obj)
            except Exception as exc:
                # Roll back any already-committed entries on partial failure
                for chid in committed:
                    try:
                        del store._objects[chid]
                        del store._handles[chid]
                    except Exception:
                        pass
                raise RuntimeError(
                    f"Failed to commit staged object {hid}: {exc}"
                ) from exc
            committed.append(hid)
        return committed

    def discard(self) -> None:
        """Discard all staged objects without publishing."""
        self._objects.clear()
        self._handles.clear()
        self._revisions.clear()

    @property
    def staged_count(self) -> int:
        return len(self._objects)


# ═══════════════════════════════════════════════════════════════════════════════
# BuildCommitBundle — atomic commit bundle (§2.13)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class BuildCommitBundle:
    """Atomic commit bundle for geometry + topology + node bindings + cache.

    The bundle collects all state produced by a single operation execution:
      - staged_objects: geometry objects not yet in ObjectStore
      - staged_registry: topology entities not yet in TopologyRegistry
      - staged_node_bindings: node output bindings (node_id → {name: id})
      - staged_events: topology events log entries
      - staged_cache_entry: cache data for future replay

    Validate-first-then-commit semantics:
      1. Execute geometry operation → stage objects
      2. Extract history → stage registry delta
      3. Validate coverage → stage events
      4. validate() checks all constraints
      5. If valid: commit() atomically publishes all staged state
      6. If invalid: rollback() discards all staged state

    This ensures no "geometry persisted but topology failed" split-brain
    and no "cache has geometry but no topology fragment" inconsistency.
    """

    staged_objects: StagedObjectStore = field(default_factory=StagedObjectStore)
    staged_node_bindings: dict[str, dict[str, str]] = field(default_factory=dict)
    staged_events: list[dict] = field(default_factory=list)
    staged_cache_entry: dict | None = None

    # Reference to external state (set at commit time)
    _registry: Any = None  # TopologyRegistry (set via set_registry)
    _node_outputs_ref: Any = None  # ctx.node_outputs dict ref
    _cache_ref: Any = None  # OperationCache ref

    def set_registry(self, registry: Any) -> None:
        """Bind the registry to commit staged topology into."""
        self._registry = registry

    def bind_node(self, node_id: str, output_name: str, handle_id: str) -> None:
        """Stage a node output binding."""
        self.staged_node_bindings.setdefault(node_id, {})[output_name] = handle_id

    def add_event(self, event: dict) -> None:
        """Stage a topology event."""
        self.staged_events.append(event)

    # ── Validation ──

    def validate(self) -> list[str]:
        """Validate all staged state before commit.

        Returns:
            List of error messages. Empty list means all valid.
        """
        errors: list[str] = []

        # Check: staged objects exist
        if self.staged_objects.staged_count == 0:
            errors.append("BuildCommitBundle: no staged objects to commit")

        # Check: staged node bindings reference valid handle IDs
        for node_id, bindings in self.staged_node_bindings.items():
            for name, hid in bindings.items():
                if not self.staged_objects.contains(hid):
                    errors.append(
                        f"BuildCommitBundle: node '{node_id}' binds output "
                        f"'{name}' to handle '{hid}' which is not in "
                        f"staged_objects"
                    )

        # Check: cache entry, if present, has required fields
        if self.staged_cache_entry is not None:
            required = ("geometry_result", "topology_registry_fragment")
            for key in required:
                if key not in self.staged_cache_entry:
                    errors.append(
                        f"BuildCommitBundle: staged_cache_entry missing "
                        f"required key '{key}'"
                    )

        return errors

    # ── Commit / Rollback ──

    def commit(self, ctx: Any) -> None:
        """Atomically publish all staged state to the runtime context.

        Args:
            ctx: RuntimeContext with object_store, topology_registry,
                 node_outputs, topology_events, and cache.

        Raises:
            RuntimeError: If validate() would fail or commit is partial.
        """
        errors = self.validate()
        if errors:
            raise RuntimeError(
                f"BuildCommitBundle validation failed before commit: "
                f"{'; '.join(errors)}"
            )

        # 1. Commit staged objects to ObjectStore
        self.staged_objects.commit_to(ctx.object_store)

        # 2. Commit node bindings
        for node_id, bindings in self.staged_node_bindings.items():
            for name, hid in bindings.items():
                ctx.bind_node_output(node_id, name, hid)

        # 3. Append staged events
        for event in self.staged_events:
            ctx.topology_events.append(event)

        # 4. Write cache entry (fragment for future topology-aware replay)
        if self.staged_cache_entry is not None:
            # Store alongside operation result for future cache.get()
            ctx._last_bundle_cache_entry = self.staged_cache_entry

        # 5. Clear staging (prevent double-commit)
        self.staged_objects.discard()

    def rollback(self) -> None:
        """Discard all staged state without publishing anything."""
        self.staged_objects.discard()
        self.staged_node_bindings.clear()
        self.staged_events.clear()
        self.staged_cache_entry = None
