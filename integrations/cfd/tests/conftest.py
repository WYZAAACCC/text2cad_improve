import json
from pathlib import Path

import pytest
from seekflow_cfd.backends import MockBackend
from seekflow_cfd.models import SimulationSpec
from seekflow_cfd.orchestrator import CFDOrchestrator
from seekflow_cfd.topology import MockTopology


@pytest.fixture
def spec():
    return SimulationSpec.model_validate(
        json.loads((Path(__file__).parents[1] / "examples/mock_spec.json").read_text())
    )


@pytest.fixture
def make_runner(tmp_path, spec):
    def make(backend=None, topology_factory=None, experts=None):
        keys = [b.surface.key for b in spec.boundary_specs]
        return CFDOrchestrator(
            tmp_path / "output",
            tmp_path,
            backend or MockBackend(),
            topology_factory or (lambda g: MockTopology(g, keys)),
            experts,
        )

    return make
