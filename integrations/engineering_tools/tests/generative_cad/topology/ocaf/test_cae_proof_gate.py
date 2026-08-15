"""CAE proof gate uses structured proof metadata instead of string matching."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.topology.ocaf.cae_preflight import (
    run_cae_preflight,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    CaeBinding,
    ProofClass,
    SelectionResolution,
    SelectionResolutionStatus,
)


class _HeuristicService:
    def solve(self, selection_id, valid_labels, deleted_shapes=()):
        return SelectionResolution(
            status=SelectionResolutionStatus.UNIQUE,
            selection_id=selection_id,
            resolved_shapes=(),
            proof=ProofClass.HEURISTIC_CANDIDATE,
        )


class TestCaeProofGate:
    def test_heuristic_proof_is_rejected(self):
        binding = CaeBinding(
            binding_id="b1",
            selection_id="s1",
            analysis_role="load",
            required=True,
            require_native_proof=True,
        )
        result = run_cae_preflight(
            [binding], _HeuristicService(), None,
        )
        assert not result.ok
        assert result.bindings[0]["detail"] == (
            "Rejected: heuristic proof not allowed for b1"
        )
