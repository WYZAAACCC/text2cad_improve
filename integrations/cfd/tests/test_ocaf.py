"""Real native OCAF proof: annulus boundary survives a radius perturbation.

No solver license is used. This validates native selection/remapping, not mesh
transfer in Fluent (that is an explicit local adapter acceptance test).
"""

import pytest

pytest.importorskip("cadquery")
pytest.importorskip("seekflow_engineering_tools")


def bundle(root, session, body, revision):
    import cadquery as cq
    from seekflow_cfd.models import GeometryRef
    from seekflow_cfd.storage import atomic_json, file_hash

    path = root / revision
    path.mkdir()
    cq.exporters.export(body, str(path / "model.step"))
    session.label_index.save_to_ocaf(session.main_label)
    session.repository.save_to(path / "design.xbf")
    history = {
        "lineage_id": "native-test",
        "revision_id": revision,
        "history_complete": True,
        "geometry_hash": file_hash(path / "model.step"),
        "topology_hash": file_hash(path / "design.xbf"),
        "provenance": "test-controlled exact construction and TNaming Modify",
    }
    atomic_json(path / "history.json", history)
    return GeometryRef(
        lineage_id="native-test",
        revision_id=revision,
        cad_record_id="native-fixture",
        geometry={"path": revision + "/model.step", "sha256": history["geometry_hash"]},
        topology={"path": revision + "/design.xbf", "sha256": history["topology_hash"]},
        history_evidence={
            "path": revision + "/history.json",
            "sha256": file_hash(path / "history.json"),
        },
        length_unit="mm",
    )


@pytest.fixture
def native_bundle(tmp_path):
    import cadquery as cq
    from OCP.TNaming import TNaming_Builder
    from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
        OcafDocumentSession,
    )
    from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
        SelectionPolicy,
        TopologyEntityKind,
    )
    from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
        PersistentSelectionService,
    )

    session = OcafDocumentSession.create()
    session.set_lineage_metadata("native-test")
    body = cq.Workplane("XY").circle(30).circle(5).extrude(10).val()
    face = body.faces(">Z")
    component = session.ensure_component("ring")
    feature = session.ensure_feature(component, "extrude")
    TNaming_Builder(feature.FindChild(2, True)).Generated(body.wrapped)
    svc = PersistentSelectionService(session)
    svc.create(
        "cooling_top",
        face.wrapped,
        body.wrapped,
        SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
    )
    ref = bundle(tmp_path, session, body, "rev-000001")
    yield session, body, face, feature, ref
    session.close()


def test_real_ocaf_resolve_and_reject_missing(tmp_path, native_bundle):
    from seekflow_cfd.models import CFDError, SurfaceRef
    from seekflow_cfd.topology import OCAFTopology

    bridge = OCAFTopology(tmp_path, native_bundle[-1])
    try:
        roles = bridge.list_topology_roles()
        assert any(r["key"] == "cooling_top" for r in roles)
        binding = bridge.resolve_role_to_faces(
            SurfaceRef(source="selection", key="cooling_top")
        )
        assert binding.status == "unique" and binding.proof == "exact_kernel_history"
        assert len(bridge.live_shapes) == 1
        with pytest.raises(CFDError):
            bridge.resolve_role_to_faces(SurfaceRef(source="selection", key="absent"))
    finally:
        bridge.close()


def test_radius_perturbation_native_identity(tmp_path, native_bundle):
    import cadquery as cq
    from OCP.TNaming import TNaming_Builder
    from seekflow_cfd.models import SurfaceRef
    from seekflow_cfd.topology import OCAFTopology, check_role_binding_stable

    session, _body, face, feature, old_ref = native_bundle
    new_body = cq.Workplane("XY").circle(32).circle(5).extrude(10).val()
    new_face = new_body.faces(">Z")
    modifier = feature.FindChild(50, True)
    TNaming_Builder(modifier).Modify(face.wrapped, new_face.wrapped)
    session._revision_number = 2
    session.set_lineage_metadata("native-test")
    new_ref = bundle(tmp_path, session, new_body, "rev-000002")
    old, new = OCAFTopology(tmp_path, old_ref), OCAFTopology(tmp_path, new_ref)
    try:
        comparison = check_role_binding_stable(
            old, new, SurfaceRef(source="selection", key="cooling_top")
        )
        assert comparison["stable"] and not comparison["mock"]
        resolved = cq.Shape.cast(next(iter(new.live_shapes.values())))
        assert resolved.Area() == pytest.approx(new_face.Area(), rel=1e-6)
    finally:
        old.close()
        new.close()


def test_isolated_native_face_export(tmp_path, native_bundle):
    import sys
    from pathlib import Path

    if not sys.platform.startswith("linux") or not Path("/proc/self/stat").is_file():
        pytest.skip("Default subprocess supervisor is Linux-only")
    from seekflow_cfd.models import Budget, SurfaceRef
    from seekflow_cfd.topology import IsolatedOCAFTopology

    job = tmp_path / "job"
    job.mkdir()
    bridge = IsolatedOCAFTopology(tmp_path, native_bundle[-1])
    surface = SurfaceRef(source="selection", key="cooling_top")
    bridge.prepare([surface], job, 30, Budget(memory_mb=4096))
    binding = bridge.resolve_role_to_faces(surface)
    assert len(binding.native_face_artifacts) == 1
    assert all(
        (job / p).stat().st_size > 0 for p in binding.native_face_artifacts.values()
    )


def test_native_worker_exports_actual_brep(tmp_path, native_bundle):
    import json
    import subprocess
    import sys

    import cadquery as cq
    from seekflow_cfd.storage import atomic_json

    job = tmp_path / "export-job"
    job.mkdir()
    atomic_json(
        job / "request.json",
        {
            "call_id": "native-export",
            "input_root": str(tmp_path),
            "geometry": native_bundle[-1].model_dump(mode="json"),
            "surfaces": [{"source": "selection", "key": "cooling_top"}],
        },
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "seekflow_cfd.topology_worker",
            "request.json",
            "response.json",
        ],
        cwd=job,
        check=True,
        timeout=30,
    )
    result = json.loads((job / "response.json").read_text())
    assert "error" not in result, result
    binding = result["bindings"]["cooling_top"]
    assert len(binding["native_face_artifacts"]) == 1
    shape = cq.Shape.importBrep(
        str(job / next(iter(binding["native_face_artifacts"].values())))
    )
    assert shape.Area() == pytest.approx(native_bundle[2].Area())
