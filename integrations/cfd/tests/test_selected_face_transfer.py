from __future__ import annotations

import json
from pathlib import Path

import pytest

cq = pytest.importorskip("cadquery")

from seekflow_cfd.evidence import FaceBinding
from seekflow_cfd.models import SimulationSpec


def _spec(root: Path, geometry_hash: str) -> dict:
    source = (
        Path(__file__).parents[3]
        / "_cfd_experiment/dev/specs/d01_outer_fluent_steady_lowre.json"
    )
    data = json.loads(source.read_text(encoding="utf-8"))
    data["geometry_ref"]["geometry"]["path"] = "model.step"
    data["geometry_ref"]["geometry"]["sha256"] = geometry_hash
    data["geometry_ref"]["topology"]["sha256"] = "1" * 64
    data["geometry_ref"]["history_evidence"]["sha256"] = "2" * 64
    data["domain_strategy"]["outer_bounds_m"] = [
        -0.05,
        -0.05,
        -0.06,
        0.05,
        0.05,
        0.06,
    ]
    for boundary in data["boundary_specs"]:
        if boundary["name"] == "disc_wall":
            boundary["surface"] = {
                "source": "selection",
                "key": "cooling_top",
                "cardinality": "exact_one",
            }
    data["boundary_specs"].append(
        {
            "name": "remaining_disc_wall",
            "surface": {
                "source": "generated",
                "key": "solid_wall",
                "cardinality": "set_allowed",
            },
            "kind": "wall",
            "velocity_m_s": None,
            "mass_flow_kg_s": None,
            "gauge_pressure_pa": None,
            "temperature_k": None,
            "heat_flux_w_m2": None,
            "thermal": "adiabatic",
            "peer": None,
            "periodic_transform": None,
            "turbulence_intensity": None,
            "hydraulic_diameter_m": None,
        }
    )
    return data


def test_named_brep_face_becomes_unique_fluid_boundary(tmp_path):
    from _cfd_experiment.local.fluent_worker import _domain_construct
    from seekflow_cfd.storage import file_hash

    body = cq.Workplane("XY").circle(20).circle(5).extrude(10).val()
    step = tmp_path / "model.step"
    cq.exporters.export(body, str(step))
    face = body.faces(">Z")
    face_path = tmp_path / "selected_face.brep"
    face.exportBrep(str(face_path))

    geometry_hash = file_hash(step)
    spec_data = _spec(tmp_path, geometry_hash)
    spec = SimulationSpec.model_validate(spec_data)
    binding = FaceBinding(
        source_key="cooling_top",
        status="unique",
        proof="exact_kernel_history",
        entity_ids=["ocaf:test-face"],
        lineage_id=spec.geometry_ref.lineage_id,
        revision_id=spec.geometry_ref.revision_id,
        geometry_hash=geometry_hash,
        history_complete=True,
        provenance="test exact selected face",
        native_face_artifacts={"ocaf:test-face": "selected_face.brep"},
    )
    report = _domain_construct(
        {
            "spec": spec.model_dump(mode="json"),
            "topology": {"cooling_top": binding.model_dump(mode="json")},
        },
        tmp_path,
        str(tmp_path),
    )

    selected = FaceBinding.model_validate(
        report["boundary_map"]["disc_wall"]
    )
    remaining = FaceBinding.model_validate(
        report["boundary_map"]["remaining_disc_wall"]
    )
    assert selected.parent_entity_ids == ["ocaf:test-face"]
    assert selected.entity_ids
    assert set(selected.entity_ids).isdisjoint(remaining.entity_ids)
    evidence = json.loads(
        (tmp_path / "domain_selection_transfer.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["selected_face_count"] == 1
    assert evidence["transfer_evidence"]["cooling_top"]["matches"][0][
        "distance_m"
    ] <= evidence["transfer_evidence"]["cooling_top"]["tolerance_m"]
