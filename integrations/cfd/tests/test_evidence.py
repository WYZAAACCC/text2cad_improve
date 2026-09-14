import pytest
from seekflow_cfd.evidence import Sample, convergence, imbalance, mesh_independence
from seekflow_cfd.models import CFDError


def history(spec, residual=1e-9, flux=1):
    return [
        Sample(
            iteration=i,
            residuals={k: residual for k in spec.convergence_criteria.residuals},
            mass_flux_kg_s={"inlet": -1, "outlet": flux, "wall": 0},
            courant=0.1,
            monitors={"outlet_pressure": 1},
        )
        for i in range(1, 5)
    ]


def test_balance_uses_sources_and_storage():
    assert imbalance({"in": -1, "out": 0.5}, source=0, storage=0.5) == 0
    assert imbalance({"in": 0, "out": 0}, source=1, storage=0) == 1


def test_residuals_alone_do_not_converge(spec):
    assert convergence(spec, history(spec, flux=2))["state"] == "continue"
    assert convergence(spec, history(spec))["state"] == "converged"


def test_missing_flux_and_nan(spec):
    h = history(spec)
    h[0].mass_flux_kg_s.pop("wall")
    with pytest.raises(CFDError):
        convergence(spec, h)
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Sample.model_validate({**h[0].model_dump(), "courant": float("nan")})


def test_nonmonotonic_or_incomplete_history(spec):
    h = history(spec)
    h[-1].iteration = 2
    with pytest.raises(CFDError):
        convergence(spec, h)
    assert convergence(spec, history(spec)[:1])["state"] == "continue"


def test_monitor_stability(spec):
    h = history(spec)
    h[-1].monitors["outlet_pressure"] = 100
    assert convergence(spec, h)["state"] == "continue"


def test_mesh_independence_not_claimed_for_mock():
    assert not mesh_independence([{"status": "success", "is_mock": True}] * 3, "x")[
        "verified"
    ]
