"""Strict bridge to the existing OCAF service; no geometric nearest-face fallback."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from .evidence import FaceBinding
from .models import CFDError, GeometryRef, SurfaceRef
from .storage import confined, file_hash


def verify_geometry(root: Path, ref: GeometryRef):
    for artifact in (ref.geometry, ref.topology, ref.history_evidence):
        path = confined(root, artifact.path)
        if not path.is_file() or file_hash(path) != artifact.sha256:
            raise CFDError(
                "cad_artifact_changed",
                f"Missing or changed CAD artifact: {artifact.path}",
                "topology",
            )
    evidence = json.loads(
        confined(root, ref.history_evidence.path).read_text(encoding="utf-8")
    )
    expected = {
        "lineage_id": ref.lineage_id,
        "revision_id": ref.revision_id,
        "geometry_hash": ref.geometry.sha256,
        "topology_hash": ref.topology.sha256,
        "history_complete": True,
    }
    if evidence.get("history_complete") is not True or any(
        evidence.get(k) != v for k, v in expected.items()
    ):
        raise CFDError(
            "history_unproven",
            "Require revision-bound complete history evidence from CAD capture",
            "topology",
        )
    return evidence


class OCAFTopology:
    """Open an immutable revision bundle. Use inside an isolated local worker.

    `live_shapes` holds opaque current-session handles, not persistent face IDs.
    Local domain adapters MUST consume these actual shapes / named BRep exports;
    STEP import ordering and fingerprints cannot establish identity.
    """

    is_mock = False

    def __init__(self, root: Path, geometry: GeometryRef):
        history = verify_geometry(root, geometry)
        try:
            from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
                collect_tnaming_labels,
            )
            from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
                OcafDocumentSession,
            )
            from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
                PersistentSelectionService,
            )
        except ImportError as exc:
            raise CFDError(
                "ocaf_unavailable",
                "Install engineering-tools and CadQuery/OCP locally",
                "topology",
                "capability_gap",
            ) from exc
        self.geometry = geometry
        self.session = OcafDocumentSession.open(confined(root, geometry.topology.path))
        self.service = PersistentSelectionService(self.session)
        self.labels = collect_tnaming_labels(self.session.design_root_label)
        self.live_shapes = {}
        meta = self.session.get_lineage_metadata()
        metadata_lineage = meta.get("lineage_id")
        revision_matches = (
            not geometry.revision_id.startswith("rev-")
            or geometry.revision_id == f"rev-{self.session.revision_number:06d}"
        )
        if metadata_lineage is None:
            # Legacy bundles may predate lineage metadata in the XBF. Accept
            # only the hash-bound history sidecar, never a caller-supplied
            # lineage string disconnected from the immutable artifacts.
            if (
                history.get("lineage_id") != geometry.lineage_id
                or history.get("revision_id") != geometry.revision_id
                or not revision_matches
            ):
                self.close()
                raise CFDError(
                    "wrong_lineage",
                    "XBF lacks metadata and history sidecar disagrees with geometry reference",
                    "topology",
                )
            self.metadata_source = "hash_bound_history_sidecar"
        else:
            if metadata_lineage != geometry.lineage_id or not revision_matches:
                self.close()
                raise CFDError(
                    "wrong_lineage",
                    "XBF lineage/revision disagrees with geometry reference",
                    "topology",
                )
            self.metadata_source = "xbf"

    def list_topology_roles(self):
        return [
            {
                "kind": e.key.object_kind,
                "namespace": e.key.namespace,
                "key": e.key.object_id,
                "label_path": list(e.tag_path.tags),
            }
            for e in self.session.label_index.entries()
            if e.retired_revision is None
            and e.key.object_kind in {"selection", "face_role", "edge_role"}
        ]

    def resolve_role_to_faces(self, surface: SurfaceRef) -> FaceBinding:
        if surface.source != "selection":
            raise CFDError(
                "domain_surface_pending",
                "Generated surfaces require domain construction history",
                "topology",
            )
        entry = self.session.label_index.get_existing(
            "selection", "lineage", surface.key
        )
        if entry is None or entry.retired_revision is not None:
            raise CFDError(
                "selection_missing", f"Selection unavailable: {surface.key}", "topology"
            )
        resolution = self.service.solve(surface.key, self.labels)
        status = resolution.status.value
        proof = resolution.proof.value if resolution.proof is not None else None
        if status not in {"unique", "set"} or proof not in {
            "exact_kernel_history",
            "exact_construction",
        }:
            raise CFDError(
                "topology_unresolved",
                resolution.detail or status,
                "topology",
                resolution_status=status,
                proof=proof,
            )
        # Existing service allows a largest_area policy. CFD explicitly forbids it.
        label = entry.tag_path.resolve(self.session.main_label)
        policy = self.service._read_policy(label)
        if policy is None or policy.split_strategy is not None:
            raise CFDError(
                "selection_policy",
                "CFD requires explicit policy without geometric split selection",
                "topology",
            )
        from OCP.TopAbs import TopAbs_FACE

        shapes = resolution.resolved_shapes
        if not shapes or any(s.ShapeType() != TopAbs_FACE for s in shapes):
            raise CFDError(
                "not_face", "CFD boundary selection must resolve only faces", "topology"
            )
        if surface.cardinality == "exact_one" and len(shapes) != 1:
            raise CFDError(
                "topology_split", "Face split requires explicit set_allowed", "topology"
            )
        ids = []
        for shape in shapes:
            handle = next(
                (
                    key
                    for key, previous in self.live_shapes.items()
                    if previous.IsSame(shape)
                ),
                None,
            )
            if handle is None:
                handle = "ocaf:" + uuid.uuid4().hex
                self.live_shapes[handle] = shape
            ids.append(handle)
        g = self.geometry
        return FaceBinding(
            source_key=surface.key,
            status=status,
            proof=proof,
            entity_ids=ids,
            lineage_id=g.lineage_id,
            revision_id=g.revision_id,
            geometry_hash=g.geometry.sha256,
            history_complete=True,
            provenance="TNaming_Selector:" + ":".join(map(str, entry.tag_path.tags)),
        )

    def export_topology_face_map(self, surfaces: list[SurfaceRef]):
        return {
            s.key: self.resolve_role_to_faces(s).model_dump(mode="json")
            for s in surfaces
        }

    def close(self):
        self.session.close()


class MockTopology:
    """Synthetic fixture only. Does not claim OCAF proof was executed."""

    is_mock = True

    def __init__(self, geometry: GeometryRef, keys: list[str]):
        self.geometry = geometry
        self.keys = keys

    def list_topology_roles(self):
        return [{"kind": "selection", "key": key, "mock": True} for key in self.keys]

    def resolve_role_to_faces(self, surface: SurfaceRef):
        if surface.source != "selection" or surface.key not in self.keys:
            raise CFDError(
                "topology_unresolved", "Unknown synthetic selection", "topology"
            )
        g = self.geometry
        return FaceBinding(
            source_key=surface.key,
            status="unique",
            proof="exact_construction",
            entity_ids=["mock:" + surface.key],
            lineage_id=g.lineage_id,
            revision_id=g.revision_id,
            geometry_hash=g.geometry.sha256,
            history_complete=True,
            provenance="MOCK_FIXTURE_ONLY",
        )

    def export_topology_face_map(self, surfaces):
        return {
            s.key: self.resolve_role_to_faces(s).model_dump(mode="json")
            for s in surfaces
        }


def check_role_binding_stable(old, new, surface: SurfaceRef):
    if old.geometry.lineage_id != new.geometry.lineage_id:
        raise CFDError(
            "lineage_changed", "Cross-lineage remapping is not allowed", "topology"
        )
    a = old.resolve_role_to_faces(surface)
    b = new.resolve_role_to_faces(surface)
    return {
        "stable": True,
        "selection_id": surface.key,
        "old": a.model_dump(mode="json"),
        "new": b.model_dump(mode="json"),
        "proof": "persistent_selection_re_solved_in_both_revisions",
        "mock": old.is_mock or new.is_mock,
    }


class IsolatedOCAFTopology:
    """Recommended production bridge: batch native OCAF work in a supervised process.

    Resolve all selections together so overlapping actual faces share a handle.
    Export each actual face as BRep; the domain worker must import these named
    artifacts, never reconstruct identity by matching STEP face numbers.
    """

    is_mock = False

    def __init__(self, root, geometry, supervisor=None):
        self.supervisor = supervisor
        self.root = Path(root).resolve()
        self.geometry = geometry
        self._bindings = {}
        self._roles = []

    def prepare(self, surfaces, job_dir, timeout_s, budget):
        import sys

        from .process import run_worker
        from .storage import atomic_json

        call_id = uuid.uuid4().hex
        request = "topology-" + call_id + ".request.json"
        response = "topology-" + call_id + ".response.json"
        atomic_json(
            job_dir / request,
            {
                "input_root": str(self.root),
                "geometry": self.geometry.model_dump(mode="json"),
                "surfaces": [s.model_dump(mode="json") for s in surfaces],
                "call_id": call_id,
            },
        )
        (self.supervisor or run_worker)(
            [sys.executable, "-m", "seekflow_cfd.topology_worker", request, response],
            job_dir,
            timeout_s,
            budget.cpu_count,
            budget.memory_mb,
            budget.max_output_bytes,
            "topology-" + call_id,
        )
        data = json.loads(confined(job_dir, response).read_text(encoding="utf-8"))
        if data.get("call_id") != call_id:
            raise CFDError(
                "topology_worker_protocol",
                "Topology worker identity mismatch",
                "topology",
                "failed",
            )
        if data.get("error"):
            e = data["error"]
            raise CFDError(
                e["code"], e["message"], "topology", e.get("status", "rejected")
            )
        self._roles = data["roles"]
        self._bindings = {
            key: FaceBinding.model_validate(value)
            for key, value in data["bindings"].items()
        }

    def list_topology_roles(self):
        return self._roles

    def resolve_role_to_faces(self, surface):
        if surface.key not in self._bindings:
            raise CFDError(
                "selection_missing",
                "Selection absent from native worker output",
                "topology",
            )
        return self._bindings[surface.key]

    def export_topology_face_map(self, surfaces):
        return {
            s.key: self.resolve_role_to_faces(s).model_dump(mode="json")
            for s in surfaces
        }


def publish_history_evidence(
    root: Path,
    output_path: str,
    *,
    lineage_id: str,
    revision_id: str,
    geometry_path: str,
    topology_path: str,
    capture_session,
):
    """Project a live, nonempty existing TopologyCaptureSession to a CFD sidecar.

    Call from an independent post-generation integration while capture is live.
    Missing capture evidence is not reconstructed from shape fingerprints.
    """
    from .models import Artifact
    from .storage import atomic_json

    if (
        capture_session.batch_count == 0
        or not capture_session.history_complete
        or capture_session.validate_all()
    ):
        raise CFDError(
            "history_unproven",
            "Native capture is empty, incomplete or invalid",
            "topology",
        )
    evidence = {
        "schema_version": "cfd_history_v1",
        "lineage_id": lineage_id,
        "revision_id": revision_id,
        "geometry_hash": file_hash(confined(root, geometry_path)),
        "topology_hash": file_hash(confined(root, topology_path)),
        "history_complete": True,
        "batch_count": capture_session.batch_count,
        "node_order": capture_session.node_order,
        "missing_history_phases": capture_session.missing_history_phases,
    }
    path = confined(root, output_path)
    atomic_json(path, evidence)
    return Artifact(path=output_path, sha256=file_hash(path))
