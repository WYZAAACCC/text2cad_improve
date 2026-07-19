"""TopologyTransaction — atomic commit/rollback for topology registry changes.

Provides a context manager that stages all topology operations (register_entity,
apply_delta) and only commits them to the real registry when the block exits
without exception and integrity validation passes.

Usage in handlers:
    with TopologyTransaction(ctx.topology_registry) as tx:
        records = build_entity_records_from_delta(delta, document_id=doc_id)
        for rec in records:
            tx.register_entity(rec)
        tx.apply_delta(delta)
    # On __exit__: validate integrity → commit or rollback
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry
    from seekflow_engineering_tools.generative_cad.topology.models import (
        TopologyDelta,
        TopologyEntityRecord,
    )


class TopologyTransaction:
    """Staged topology state for atomic commit/rollback.

    Wraps a TopologyRegistry, providing:
      - clone(): creates an independent copy for staging
      - register_entity(): writes to the staged copy
      - apply_delta(): writes to the staged copy
      - commit(): atomically replaces the original registry's state
      - rollback(): discards all staged changes

    Context manager usage ensures commit on success, rollback on exception.
    """

    def __init__(
        self,
        registry: "TopologyRegistry",
        *,
        object_store: Any | None = None,
    ) -> None:
        self._original = registry
        self._staged: "TopologyRegistry | None" = None
        self._committed = False
        self._object_store = object_store  # V3: geometry verification

    # ── Context manager ──

    def __enter__(self) -> "TopologyTransaction":
        self._staged = self._original.clone()
        self._committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> bool:
        if exc_type is not None:
            # Exception occurred — rollback
            self.rollback()
            return False  # propagate exception

        if self._committed:
            # Already committed explicitly — no-op
            return False

        # No exception — validate and commit
        try:
            self.commit()
        except Exception:
            self.rollback()
            raise
        return False

    # ── Registration (delegates to staged registry) ──

    def register_entity(self, record: "TopologyEntityRecord") -> None:
        """Register an entity in the staged registry."""
        if self._staged is None:
            raise RuntimeError("TopologyTransaction not entered — use 'with' statement")
        self._staged.register_entity(record)

    def apply_delta(self, delta: "TopologyDelta") -> None:
        """Apply a topology delta to the staged registry."""
        if self._staged is None:
            raise RuntimeError("TopologyTransaction not entered — use 'with' statement")
        self._staged.apply_delta(delta)

    # ── Commit / Rollback ──

    def commit(self) -> None:
        """Validate staged registry integrity and atomically commit to original.

        Raises:
            ValueError: If integrity check fails.
            RuntimeError: If transaction was not entered.
        """
        if self._staged is None:
            raise RuntimeError("TopologyTransaction not entered — nothing to commit")

        result = self._staged.validate_integrity()
        if not result.get("ok"):
            issues = result.get("issues", [])
            issue_codes = [i.get("code", "?") for i in issues[:5]]
            raise ValueError(
                f"TopologyTransaction integrity check failed: "
                f"{len(issues)} issue(s) — {issue_codes}"
            )

        # Atomically replace original state with staged state
        self._original._replace_from(self._staged)
        self._committed = True

    def rollback(self) -> None:
        """Discard all staged changes (no-op on original registry)."""
        self._staged = None
        self._committed = False

    # ── Properties ──

    # ── V3: Geometry verification ──

    def validate_geometry_bindings(self, delta: "TopologyDelta") -> None:
        """Verify all body handles in the delta exist in ObjectStore.

        Phase 3: existence check only. Ensures geometry is committed to
        ObjectStore before topology state is updated — preventing the
        split-brain state where Registry has records for bodies that
        don't exist or were never successfully built.

        Phase 4+: will add revision consistency check.
        """
        if self._object_store is None:
            return  # no ObjectStore → skip (test/legacy compatibility)
        for handle_id in delta.result_body_handle_ids:
            if not handle_id:
                continue
            try:
                self._object_store.get(handle_id)
            except (KeyError, AttributeError):
                raise ValueError(
                    f"TopologyTransaction: body handle {handle_id!r} "
                    f"not found in ObjectStore. Geometry must be committed "
                    f"to ObjectStore before topology delta is applied."
                )

    @property
    def staged(self) -> "TopologyRegistry":
        """Access the staged registry (for advanced use)."""
        if self._staged is None:
            raise RuntimeError("TopologyTransaction not entered")
        return self._staged

    @property
    def entity_count(self) -> int:
        """Number of entities in the staged registry."""
        if self._staged is None:
            return 0
        return self._staged.entity_count
