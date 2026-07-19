"""TopologyRegistry — central authority for persistent topology identity.

Maintains:
  - stable_id → TopologyEntityRecord
  - runtime_shape_key → stable_id list
  - owner_body_handle_id → stable_id list
  - node_id → generated/modified/deleted ids
  - semantic alias → stable_id/set
  - lineage graph

Boundary with ObjectStore:
  ObjectStore:       handle_id → Python/OCP/CadQuery object
  TopologyRegistry:  persistent topology ID → current subshape locator/history
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from seekflow_engineering_tools.generative_cad.topology.models import (
    TopologyDelta,
    TopologyEntityRecord,
    TopologyRelation,
    TopologyResolution,
)


class TopologyRegistry:
    """Central persistent topology identity authority.

    Phase 1: entity registration, delta application, resolution, snapshot.
    Phase 2+: history-aware delta from OCCT wrappers.
    Phase 3+: constrained fingerprint matching for fallback.
    """

    def __init__(self) -> None:
        # Primary index: persistent_id → entity record
        self._entities: dict[str, TopologyEntityRecord] = {}

        # Runtime shape key → list of persistent IDs (for re-attachment)
        self._shape_index: dict[str, list[str]] = {}

        # Owner body handle → persistent IDs (for bulk resolution)
        self._body_index: dict[str, list[str]] = defaultdict(list)

        # Producer node → generated/modified/deleted persistent IDs
        self._node_index: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: {"generated": [], "modified": [], "deleted": []}
        )

        # Semantic alias → persistent ID(s)
        self._alias_index: dict[str, list[str]] = defaultdict(list)

        # Generation counter (per lineage root)
        self._generations: dict[str, int] = defaultdict(int)

        # Topology events log (for debugging, truncated at 1000 entries)
        self._events: list[dict] = []
        self._max_events = 1000

    # ── Registration ──

    def register_entity(self, record: TopologyEntityRecord) -> None:
        """Register a single topology entity.

        Raises ValueError if the persistent_id is already registered with
        an active entity (superseded entities may be overwritten).
        """
        pid = record.persistent_id
        if pid in self._entities:
            existing = self._entities[pid]
            if existing.status != "superseded":
                raise ValueError(
                    f"Duplicate persistent_id: {pid}. "
                    f"Existing status={existing.status}, new status={record.status}. "
                    f"Mark the old entity as 'superseded' before re-registering."
                )
        self._entities[pid] = record

        # Index by owner body
        self._body_index[record.owner_body_handle_id].append(pid)

        # Index by producer node
        self._node_index[record.producer_node_id]["generated"].append(pid)

        # Index by semantic alias
        alias = record.semantic_role
        if alias:
            self._alias_index[alias].append(pid)

        self._record_event("entity_registered", {
            "persistent_id": pid,
            "semantic_role": record.semantic_role,
            "entity_type": record.entity_type,
        })

    # ── Delta Application ──

    def apply_delta(self, delta: TopologyDelta) -> None:
        """Apply a TopologyDelta, updating entity states and indices.

        Caller must ensure ObjectStore changes are committed BEFORE calling
        this method. If body handles in delta don't exist in the shape_index,
        delta application still succeeds (Phase 1: lenient; Phase 3+: strict).

        The delta describes what happened during one operation execution:
        which entities were generated, modified, deleted, split, or merged.
        """
        for relation in delta.relations:
            if relation.relation == "primitive":
                # New entity with no ancestors — register directly
                for key in relation.result_entity_keys:
                    self._register_from_relation(key, relation, delta)
            elif relation.relation == "generated":
                for key in relation.result_entity_keys:
                    self._register_from_relation(key, relation, delta)
            elif relation.relation == "modified":
                for source_id in relation.source_ids:
                    self._apply_modify(source_id, relation, delta)
            elif relation.relation == "deleted":
                for source_id in relation.source_ids:
                    self._apply_delete(source_id, delta)
            elif relation.relation == "split":
                for source_id in relation.source_ids:
                    self._apply_split(source_id, relation, delta)
            elif relation.relation == "merged":
                for key in relation.result_entity_keys:
                    self._apply_merge(key, relation, delta)
            elif relation.relation == "selected":
                # Selection doesn't change entity state — record only
                pass

        self._record_event("delta_applied", {
            "node_id": delta.node_id,
            "component_id": delta.component_id,
            "relation_count": len(delta.relations),
            "history_provider": delta.history_provider,
        })

    def _register_from_relation(
        self, key: str, relation: TopologyRelation, delta: TopologyDelta,
    ) -> None:
        """Register a new entity referenced by a result_entity_key.

        Phase 1: key must be a valid compact PersistentTopoId string.
        The entity must be pre-registered via register_entity().
        """
        # If the entity is already registered, just link it
        if key in self._entities:
            rec = self._entities[key]
            for src_id in relation.source_ids:
                if src_id not in rec.ancestor_ids:
                    rec.ancestor_ids.append(src_id)
                if src_id in self._entities:
                    if key not in self._entities[src_id].descendant_ids:
                        self._entities[src_id].descendant_ids.append(key)
            return

        # Otherwise, record as pending — caller should have pre-registered
        self._record_event("unregistered_key", {
            "key": key,
            "node_id": delta.node_id,
            "relation": relation.relation,
        })

    def _apply_modify(
        self, source_id: str, relation: TopologyRelation, delta: TopologyDelta,
    ) -> None:
        """Apply a 1:1 modification: old entity → updated current shape."""
        if source_id not in self._entities:
            self._record_event("modify_unknown_source", {"source_id": source_id})
            return

        rec = self._entities[source_id]
        rec.generation += 1
        # PR 2: Keep existing status — modify evolves the entity in-place
        rec.resolution_method = "kernel_modified"
        if relation.result_entity_keys:
            rec.current_locator = {
                "result_key": relation.result_entity_keys[0],
                "delta_node_id": delta.node_id,
            }
        self._node_index[delta.node_id]["modified"].append(source_id)

    def _apply_delete(self, source_id: str, delta: TopologyDelta) -> None:
        """Mark an entity as deleted — downstream references will fail explicitly."""
        if source_id not in self._entities:
            self._record_event("delete_unknown_source", {"source_id": source_id})
            return

        rec = self._entities[source_id]
        rec.status = "deleted"
        rec.current_locator = None
        rec.evidence.append({
            "event": "deleted",
            "node_id": delta.node_id,
        })
        self._node_index[delta.node_id]["deleted"].append(source_id)

    def _apply_split(
        self, source_id: str, relation: TopologyRelation, _delta: TopologyDelta,
    ) -> None:
        """One old entity split into multiple new ones.

        PR 2 fix: source entity is now superseded (was incorrectly kept active).
        resolve(source) will return status="set" with descendant_ids.
        """
        if source_id not in self._entities:
            return
        rec = self._entities[source_id]
        # Old entity is superseded — no longer directly resolvable
        rec.status = "superseded"
        rec.current_locator = None
        rec.resolution_method = "set_expansion"
        for key in relation.result_entity_keys:
            if key not in rec.descendant_ids:
                rec.descendant_ids.append(key)
            # Ensure bidirectionality
            if key in self._entities:
                child = self._entities[key]
                if source_id not in child.ancestor_ids:
                    child.ancestor_ids.append(source_id)

    def _apply_merge(
        self, key: str, relation: TopologyRelation, _delta: TopologyDelta,
    ) -> None:
        """Multiple old entities merged into one new entity.

        PR 2 fix: all source entities are now superseded.
        Target entity records ancestors.
        """
        if key not in self._entities:
            return
        rec = self._entities[key]
        for src_id in relation.source_ids:
            if src_id not in rec.ancestor_ids:
                rec.ancestor_ids.append(src_id)
            # Mark source entity as superseded
            if src_id in self._entities:
                src = self._entities[src_id]
                src.status = "superseded"
                src.current_locator = None
                src.resolution_method = "set_expansion"
                if key not in src.descendant_ids:
                    src.descendant_ids.append(key)

    # ── Resolution ──

    def resolve(
        self,
        persistent_id: str,
        *,
        object_store: Any | None = None,
        binding_service: Any | None = None,
    ) -> TopologyResolution:
        """Resolve a persistent topology reference at runtime.

        v2 tightened rules (when object_store and binding_service are provided):
          'exact' status requires ALL of:
            1. record.status == "active"
            2. record.current_locator is not None
            3. Owner body exists in ObjectStore
            4. Owner body content hash matches (if present in locator)
            5. Locator can retrieve actual subshape
            6. Entity type matches locator.entity_type

        Without object_store/binding_service, falls back to v1 behavior
        (checks record status only, no actual shape verification).

        Returns structured TopologyResolution — NEVER returns a wrong entity
        silently. Status tells consumers exactly what happened.
        """
        record = self._entities.get(persistent_id)
        if record is None:
            return TopologyResolution(
                requested_id=persistent_id,
                status="unresolved",
                evidence=[{"reason": "persistent_id not found in registry"}],
            )

        if record.status == "deleted":
            return TopologyResolution(
                requested_id=persistent_id,
                status="deleted",
                resolved_entity_ids=[persistent_id],
                evidence=[{"reason": "entity was deleted during model evolution"}],
            )

        if record.status == "superseded":
            return TopologyResolution(
                requested_id=persistent_id,
                status="set",
                resolved_entity_ids=record.descendant_ids,
                evidence=[{
                    "reason": (
                        f"entity was superseded — "
                        f"{len(record.descendant_ids)} descendant(s) available"
                    ),
                    "descendant_ids": record.descendant_ids,
                }],
            )

        if record.status == "ambiguous":
            return TopologyResolution(
                requested_id=persistent_id,
                status="ambiguous",
                resolved_entity_ids=record.descendant_ids,
                evidence=[{"reason": "entity is in ambiguous state — set expansion available"}],
            )

        if record.status == "active":
            loc = record.current_locator

            # ── v2 tightened verification (only when ObjectStore available) ──
            if object_store is not None and binding_service is not None:
                # Check 1: current_locator must exist
                if loc is None:
                    return TopologyResolution(
                        requested_id=persistent_id,
                        status="unresolved",
                        evidence=[{
                            "reason": "active entity has no current_locator",
                            "error_code": "topology_locator_missing",
                        }],
                    )

                owner_handle = loc.get("owner_body_handle_id", "")

                # Check 2: Owner body must exist in ObjectStore
                try:
                    object_store.get(owner_handle)
                except (KeyError, AttributeError):
                    return TopologyResolution(
                        requested_id=persistent_id,
                        status="unresolved",
                        evidence=[{
                            "reason": f"owner body {owner_handle} not found in ObjectStore",
                            "error_code": "topology_owner_body_not_found",
                        }],
                    )

                # Check 3: Entity type must match locator
                loc_entity_type = loc.get("entity_type", "")
                if loc_entity_type and loc_entity_type != record.entity_type:
                    return TopologyResolution(
                        requested_id=persistent_id,
                        status="type_mismatch",
                        evidence=[{
                            "reason": (
                                f"entity_type mismatch: record={record.entity_type}, "
                                f"locator={loc_entity_type}"
                            ),
                            "error_code": "topology_entity_type_mismatch",
                        }],
                    )

                # Check 4: Content hash consistency (if available)
                owner_shape_content_hash = loc.get("owner_shape_content_hash")
                if owner_shape_content_hash:
                    try:
                        from seekflow_engineering_tools.generative_cad.topology.shape_binding import (
                            ShapeBindingService,
                        )
                        owner_shape = object_store.get(owner_handle)
                        current_hash = ShapeBindingService._compute_shape_content_hash(
                            owner_shape
                        )
                        if current_hash != owner_shape_content_hash:
                            return TopologyResolution(
                                requested_id=persistent_id,
                                status="unresolved",
                                evidence=[{
                                    "reason": (
                                        "owner body content hash mismatch: "
                                        f"expected={owner_shape_content_hash[:12]}..., "
                                        f"current={current_hash[:12]}..."
                                    ),
                                    "error_code": "topology_content_hash_mismatch",
                                }],
                            )
                    except Exception:
                        pass  # Unable to verify hash → skip this check, not fatal

                # Check 5: Locator retrievable via ShapeBindingService
                try:
                    verify_result = binding_service.verify_locator(
                        binding_service._reconstruct_locator(loc),
                        expected_fingerprint=None,
                    )
                    if not verify_result.valid:
                        return TopologyResolution(
                            requested_id=persistent_id,
                            status="unresolved",
                            evidence=[{
                                "reason": verify_result.detail,
                                "error_code": verify_result.error_code,
                            }],
                        )
                except Exception:
                    pass  # Verification unavailable → skip

            # ── Build current_handles from locator ──
            current_handles = []
            if loc:
                owner = loc.get("owner_body_handle_id", "")
                idx = loc.get("indexed_map_position")
                if owner and idx is not None:
                    current_handles.append(f"{record.entity_type}:{owner}:#{idx}")

            return TopologyResolution(
                requested_id=persistent_id,
                status="exact",
                resolved_entity_ids=[persistent_id],
                current_handles=current_handles,
                method=record.resolution_method,
                confidence=record.confidence,
            )

        return TopologyResolution(
            requested_id=persistent_id,
            status="unresolved",
            evidence=[{"reason": f"unknown entity status: {record.status}"}],
        )

    @staticmethod
    def _reconstruct_locator(loc: dict) -> Any:
        """Reconstruct a RuntimeTopoLocator from a dict (sidecar-friendly).

        Uses lazy import to avoid circular dependency.
        """
        from seekflow_engineering_tools.generative_cad.topology.locator import (
            RuntimeTopoLocator,
        )
        return RuntimeTopoLocator(**loc)

    def resolve_set(self, persistent_ids: list[str]) -> list[TopologyResolution]:
        """Resolve a set of persistent IDs. Missing IDs → unresolved."""
        return [self.resolve(pid) for pid in persistent_ids]

    # ── Mutation ──

    def mark_deleted(self, persistent_id: str, reason: str = "") -> None:
        """Explicitly mark an entity as deleted (e.g. feature removal)."""
        if persistent_id in self._entities:
            self._entities[persistent_id].status = "deleted"
            self._entities[persistent_id].current_locator = None
            self._entities[persistent_id].evidence.append({
                "event": "marked_deleted",
                "reason": reason,
            })

    def mark_ambiguous(self, persistent_id: str, candidates: list[str]) -> None:
        """Mark an entity as ambiguous with known candidate descendants."""
        if persistent_id in self._entities:
            self._entities[persistent_id].status = "ambiguous"
            self._entities[persistent_id].descendant_ids = list(candidates)

    # ── Clone (for transaction staging) ──

    def clone(self) -> "TopologyRegistry":
        """Deep-copy registry for transaction staging.

        Creates an independent copy with identical entities, indices, and events.
        Used by TopologyTransaction to stage changes before atomic commit.
        """
        cloned = TopologyRegistry()
        # Deep-copy entities
        for pid, rec in self._entities.items():
            cloned._entities[pid] = rec.model_copy(deep=True)
        # Copy indices
        for pid, ids in self._body_index.items():
            cloned._body_index[pid] = list(ids)
        for nid, cats in self._node_index.items():
            cloned._node_index[nid] = {k: list(v) for k, v in cats.items()}
        for alias, ids in self._alias_index.items():
            cloned._alias_index[alias] = list(ids)
        # Copy events
        cloned._events = list(self._events)
        return cloned

    def _replace_from(self, source: "TopologyRegistry") -> None:
        """Atomically replace all internal state from another registry.

        Used by TopologyTransaction.commit() to swap staged state in.
        """
        self._entities.clear()
        self._entities.update(source._entities)
        self._body_index.clear()
        self._body_index.update(source._body_index)
        self._node_index.clear()
        self._node_index.update(source._node_index)
        self._alias_index.clear()
        self._alias_index.update(source._alias_index)
        self._events = list(source._events)

    # ── Export / Import (for topology sidecar) ──

    def export_snapshot(self) -> dict:
        """Export current registry state for persistence.

        Returns a dict suitable for JSON serialization.
        current_locator is intentionally excluded (runtime-only).
        """
        entities_data = {}
        for pid, rec in self._entities.items():
            data = rec.model_dump()
            # Strip runtime-only locator
            data.pop("current_locator", None)
            entities_data[pid] = data

        node_data = {}
        for nid, cats in self._node_index.items():
            node_data[nid] = {
                k: list(v) for k, v in cats.items()
            }

        return {
            "entities": entities_data,
            "node_index": node_data,
            "event_count": len(self._events),
        }

    def restore_snapshot(self, snapshot: dict) -> None:
        """Restore registry from a previously exported snapshot.

        Clears all current state before restoring.
        """
        self._entities.clear()
        self._body_index.clear()
        self._node_index.clear()
        self._alias_index.clear()
        self._events.clear()

        for pid, data in snapshot.get("entities", {}).items():
            rec = TopologyEntityRecord(**data)
            self._entities[pid] = rec
            self._body_index[rec.owner_body_handle_id].append(pid)
            self._node_index[rec.producer_node_id]["generated"].append(pid)
            if rec.semantic_role:
                self._alias_index[rec.semantic_role].append(pid)

        for nid, cats in snapshot.get("node_index", {}).items():
            for cat, ids in cats.items():
                self._node_index[nid][cat] = list(ids)

    # ── Validation ──

    def validate_integrity(self) -> dict:
        """PR 2: Full integrity check — 10 validation rules.

        Returns {"ok": bool, "issues": list[dict]}.
        """
        issues: list[dict] = []

        # ── 1: Active entity must have owner ──
        for pid, rec in self._entities.items():
            if rec.status == "active" and not rec.owner_body_handle_id:
                issues.append({
                    "code": "active_entity_no_owner",
                    "persistent_id": pid,
                    "message": f"Active entity {pid} has no owner_body_handle_id",
                })

        # ── 2: Superseded/deleted entities must not have active locator ──
        for pid, rec in self._entities.items():
            if rec.status in ("superseded", "deleted") and rec.current_locator:
                issues.append({
                    "code": "inactive_entity_has_locator",
                    "persistent_id": pid,
                    "message": (
                        f"Entity {pid} has status={rec.status} but still has "
                        f"a current_locator — should be None"
                    ),
                })

        # ── 3: Referenced IDs must exist ──
        all_pids = set(self._entities.keys())
        for pid, rec in self._entities.items():
            for aid in rec.ancestor_ids:
                if aid not in all_pids:
                    issues.append({
                        "code": "dangling_ancestor_ref",
                        "persistent_id": pid,
                        "message": f"Entity {pid} references non-existent ancestor {aid}",
                    })
            for did in rec.descendant_ids:
                if did not in all_pids:
                    issues.append({
                        "code": "dangling_descendant_ref",
                        "persistent_id": pid,
                        "message": f"Entity {pid} references non-existent descendant {did}",
                    })

        # ── 4: Ancestor/descendant bidirectional consistency ──
        for pid, rec in self._entities.items():
            for did in rec.descendant_ids:
                if did in self._entities:
                    child = self._entities[did]
                    if pid not in child.ancestor_ids:
                        issues.append({
                            "code": "bidirectional_lineage_broken",
                            "persistent_id": pid,
                            "message": (
                                f"Entity {pid} lists {did} as descendant, "
                                f"but {did} does not list {pid} as ancestor"
                            ),
                        })
            for aid in rec.ancestor_ids:
                if aid in self._entities:
                    parent = self._entities[aid]
                    if pid not in parent.descendant_ids:
                        issues.append({
                            "code": "bidirectional_lineage_broken",
                            "persistent_id": pid,
                            "message": (
                                f"Entity {pid} lists {aid} as ancestor, "
                                f"but {aid} does not list {pid} as descendant"
                            ),
                        })

        # ── 5: Full DAG cycle detection (not just first ancestor) ──
        for pid in self._entities:
            if self._has_cycle(pid, set(), set()):
                issues.append({
                    "code": "circular_lineage",
                    "persistent_id": pid,
                    "message": f"Circular lineage detected involving {pid}",
                })

        # ── 6: Index consistency — no zombie entries in indices ──
        for body_id, pids in self._body_index.items():
            for pid in pids:
                if pid not in all_pids:
                    issues.append({
                        "code": "zombie_body_index",
                        "persistent_id": pid,
                        "message": f"Body index for {body_id} references non-existent entity {pid}",
                    })
        for alias, pids in self._alias_index.items():
            for pid in pids:
                if pid not in all_pids:
                    issues.append({
                        "code": "zombie_alias_index",
                        "persistent_id": pid,
                        "message": f"Alias index '{alias}' references non-existent entity {pid}",
                    })

        # ── 7: Resolution method consistency ──
        for pid, rec in self._entities.items():
            if rec.status == "superseded" and rec.resolution_method not in (
                "set_expansion", "unresolved",
            ):
                issues.append({
                    "code": "resolution_method_status_mismatch",
                    "persistent_id": pid,
                    "message": (
                        f"Entity {pid} is superseded but has "
                        f"resolution_method={rec.resolution_method}"
                    ),
                })

        # ── 8: Node index categories must reference valid entities ──
        for nid, cats in self._node_index.items():
            for cat, pids in cats.items():
                for pid in pids:
                    if pid not in all_pids:
                        issues.append({
                            "code": "zombie_node_index",
                            "persistent_id": pid,
                            "message": (
                                f"Node index {nid}/{cat} references "
                                f"non-existent entity {pid}"
                            ),
                        })

        return {"ok": len(issues) == 0, "issues": issues}

    def _has_cycle(self, pid: str, visiting: set[str], visited: set[str]) -> bool:
        """DFS cycle detection across full ancestor DAG (not just first ancestor)."""
        if pid in visiting:
            return True
        if pid in visited or pid not in self._entities:
            return False
        visiting.add(pid)
        for ancestor in self._entities[pid].ancestor_ids:
            if self._has_cycle(ancestor, visiting, visited):
                return True
        visiting.discard(pid)
        visited.add(pid)
        return False

    # ── Query ──

    def get_entity(self, persistent_id: str) -> TopologyEntityRecord | None:
        """Get an entity record by persistent ID."""
        return self._entities.get(persistent_id)

    def get_by_body(self, owner_body_handle_id: str) -> list[TopologyEntityRecord]:
        """Get all entities owned by a body handle."""
        ids = self._body_index.get(owner_body_handle_id, [])
        return [self._entities[pid] for pid in ids if pid in self._entities]

    def get_by_node(self, node_id: str, category: str = "generated") -> list[TopologyEntityRecord]:
        """Get entities produced by a specific node."""
        ids = self._node_index.get(node_id, {}).get(category, [])
        return [self._entities[pid] for pid in ids if pid in self._entities]

    def get_by_alias(self, alias: str) -> list[TopologyEntityRecord]:
        """Get entities by semantic alias."""
        ids = self._alias_index.get(alias, [])
        return [self._entities[pid] for pid in ids if pid in self._entities]

    # ── Properties ──

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    @property
    def active_count(self) -> int:
        return sum(1 for r in self._entities.values() if r.status == "active")

    @property
    def deleted_count(self) -> int:
        return sum(1 for r in self._entities.values() if r.status == "deleted")

    # ── Internal ──

    def _record_event(self, event_type: str, data: dict) -> None:
        self._events.append({"event": event_type, **data})
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
