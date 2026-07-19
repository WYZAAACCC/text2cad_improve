"""Topology matcher — constrained fingerprint matching for fallback resolution.

Phase 2: data structures + constraint framework only.
Phase 3+: actual fingerprint computation + bipartite hungarian matching.

Design constraints:
  - ALWAYS constrained by provenance, component, entity type, lineage
  - NEVER global nearest-centroid matching
  - Ambiguity margin: best/second-best score diff < threshold → ambiguous
  - Cost function: C = w_provenance*P + w_type*T + w_adjacency*A + w_geometry*G + w_location*L
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict


# ═══════════════════════════════════════════════════════════════════════════════
# Constraint types
# ═══════════════════════════════════════════════════════════════════════════════


class MatchConstraint(BaseModel):
    """Constraints that MUST be satisfied before geometric comparison.

    Any candidate failing a constraint is immediately disqualified.
    """

    model_config = ConfigDict(extra="forbid")

    same_component: bool = True
    same_entity_type: bool = True
    same_producer_operation: bool = True

    allowed_lineage_relations: list[str] = ["primitive", "generated", "modified"]


class MatchWeights(BaseModel):
    """Weights for the multi-term cost function."""

    model_config = ConfigDict(extra="forbid")

    w_provenance: float = 0.30
    w_type: float = 0.10
    w_adjacency: float = 0.25
    w_geometry: float = 0.25
    w_location: float = 0.10

    # Ambiguity threshold: if (second_best - best) / best < this, it's ambiguous
    ambiguity_margin: float = 0.05


@dataclass
class MatchCandidate:
    """One candidate entity for matching, with computed costs."""

    entity_id: str
    provenance_cost: float = 0.0
    type_cost: float = 0.0
    adjacency_cost: float = 0.0
    geometry_cost: float = 0.0
    location_cost: float = 0.0

    @property
    def total_cost(self) -> float:
        return (
            self.provenance_cost
            + self.type_cost
            + self.adjacency_cost
            + self.geometry_cost
            + self.location_cost
        )


@dataclass
class MatchResult:
    """Result of constrained fingerprint matching."""

    requested_id: str
    status: str = "unresolved"  # "exact", "ambiguous", "unresolved"
    best_match: MatchCandidate | None = None
    candidates: list[MatchCandidate] = field(default_factory=list)
    margin: float = 0.0
    evidence: list[dict] = field(default_factory=list)

    @property
    def is_exact(self) -> bool:
        return self.status == "exact"

    @property
    def is_ambiguous(self) -> bool:
        return self.status == "ambiguous"


# ═══════════════════════════════════════════════════════════════════════════════
# Matcher (Phase 2: framework only)
# ═══════════════════════════════════════════════════════════════════════════════


class ConstrainedTopologyMatcher:
    """Constrained fingerprint matcher for topology resolution fallback.

    Phase 2: constraint enforcement + candidate filtering.
    Phase 3+: actual fingerprint computation + cost evaluation.
    """

    def __init__(self, weights: MatchWeights | None = None) -> None:
        self._weights = weights or MatchWeights()
        self._constraints = MatchConstraint()

    def filter_candidates(
        self,
        candidates: list[dict],
        *,
        target_component: str,
        target_entity_type: str,
        target_producer: str | None = None,
    ) -> list[dict]:
        """Filter candidates by hard constraints (before geometric comparison).

        Any candidate failing ANY constraint is removed.
        """
        filtered = []
        for c in candidates:
            if self._constraints.same_component:
                if c.get("component_id") != target_component:
                    continue
            if self._constraints.same_entity_type:
                if c.get("entity_type") != target_entity_type:
                    continue
            if self._constraints.same_producer_operation and target_producer:
                if c.get("producer_node_id") != target_producer:
                    continue
            filtered.append(c)
        return filtered

    def rank_candidates(
        self,
        candidates: list[dict],
        target_fingerprint: dict,
    ) -> list[MatchCandidate]:
        """Rank candidates by geometric cost.

        Phase 2: returns candidates with zero costs (placeholder).
        Phase 3+: actual fingerprint comparison.
        """
        ranked = []
        for c in candidates:
            mc = MatchCandidate(
                entity_id=c.get("persistent_id", c.get("id", "")),
                provenance_cost=0.0,
                type_cost=0.0,
                adjacency_cost=0.0,
                geometry_cost=0.0,
                location_cost=0.0,
            )
            ranked.append(mc)
        ranked.sort(key=lambda x: x.total_cost)
        return ranked

    def resolve(
        self,
        candidates: list[dict],
        target_fingerprint: dict,
        *,
        target_component: str,
        target_entity_type: str,
        target_producer: str | None = None,
    ) -> MatchResult:
        """Full constrained matching pipeline.

        1. Filter by hard constraints
        2. Rank by geometric cost
        3. Check ambiguity margin
        4. Return MatchResult
        """
        filtered = self.filter_candidates(
            candidates,
            target_component=target_component,
            target_entity_type=target_entity_type,
            target_producer=target_producer,
        )

        if not filtered:
            return MatchResult(
                requested_id="",
                status="unresolved",
                evidence=[{"reason": "No candidates passed constraint filter"}],
            )

        ranked = self.rank_candidates(filtered, target_fingerprint)

        if len(ranked) == 1:
            return MatchResult(
                requested_id=ranked[0].entity_id,
                status="exact",
                best_match=ranked[0],
                candidates=ranked,
            )

        # Check ambiguity margin
        best = ranked[0]
        second = ranked[1]
        if best.total_cost == 0 and second.total_cost == 0:
            # Phase 2: all costs are zero — no geometric comparison yet
            margin = 0.0
        else:
            margin = (second.total_cost - best.total_cost) / max(best.total_cost, 1e-9)

        if margin < self._weights.ambiguity_margin:
            return MatchResult(
                requested_id=best.entity_id,
                status="ambiguous",
                best_match=best,
                candidates=ranked,
                margin=margin,
                evidence=[{
                    "reason": f"Ambiguity margin {margin:.4f} < threshold {self._weights.ambiguity_margin}",
                    "best_cost": best.total_cost,
                    "second_cost": second.total_cost,
                }],
            )

        return MatchResult(
            requested_id=best.entity_id,
            status="exact",
            best_match=best,
            candidates=ranked,
            margin=margin,
        )
