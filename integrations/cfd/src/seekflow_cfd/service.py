"""Transport-neutral API. CAD calls this service explicitly after generation."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .models import SimulationSpec
from .storage import JobStore


class CFDService:
    """Bounded local queue. Restart from durable checkpoints after server restart.

    Use one process per OCAF job in production; OCAF factories should be worker
    proxies when max_workers > 1. No CAD application imports are necessary.
    """

    def __init__(
        self, orchestrator_factory, output_root: Path, max_workers=1, max_pending=16
    ):
        import threading

        self.factory = orchestrator_factory
        self.root = Path(output_root)
        self.pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="cfd"
        )
        self.slots = threading.BoundedSemaphore(max_pending)
        self.futures = {}

    def submit(self, spec: dict):
        parsed = SimulationSpec.model_validate(spec)
        if not self.slots.acquire(blocking=False):
            raise RuntimeError("CFD queue is full")
        job_id = uuid.uuid4().hex

        def work():
            return self.factory().run(parsed, job_id=job_id)

        self.futures[job_id] = self.pool.submit(work)
        self.futures[job_id].add_done_callback(lambda _: self.slots.release())
        return {"job_id": job_id, "status": "queued"}

    def status(self, job_id):
        job = JobStore(self.root, job_id)
        future = self.futures.get(job_id)
        if future is not None:
            if future.cancelled():
                return {"job_id": job_id, "status": "cancelled_before_start"}
            if not future.done():
                return {
                    "job_id": job_id,
                    "status": "running" if future.running() else "queued",
                }
            return future.result()
        if (job.path / "record.json").exists():
            return job.read("record.json")
        return {"job_id": job_id, "status": "unknown"}

    def cancel(self, job_id):
        future = self.futures.get(job_id)
        if future is not None and future.cancel():
            return {"job_id": job_id, "status": "cancelled_before_start"}
        job = JobStore(self.root, job_id)
        (job.path / "cancel.request").touch()
        return {"job_id": job_id, "status": "cancellation_requested"}

    def resume(self, job_id):
        job = JobStore(self.root, job_id)
        existing = self.futures.get(job_id)
        if existing is not None and not existing.done():
            raise RuntimeError("Job is already queued/running")
        spec = SimulationSpec.model_validate(job.read("original_spec.json"))
        if not self.slots.acquire(blocking=False):
            raise RuntimeError("CFD queue is full")
        future = self.pool.submit(
            lambda: self.factory().run(spec, job_id=job_id, resume=True)
        )
        future.add_done_callback(lambda _: self.slots.release())
        self.futures[job_id] = future
        return {"job_id": job_id, "status": "queued"}

    def close(self):
        self.pool.shutdown(wait=True)


def register_mcp_tools(mcp, service: CFDService, topology, revisions=None):
    """Explicit registration, isolated from existing CAD MCP registry."""

    @mcp.tool()
    def cfd_submit(spec: dict) -> dict:
        """Submit an expert-confirmed declarative CFD spec."""
        return service.submit(spec)

    @mcp.tool()
    def cfd_status(job_id: str) -> dict:
        """Read CFD state and auditable results."""
        return service.status(job_id)

    @mcp.tool()
    def cfd_cancel(job_id: str) -> dict:
        """Request cancellation at a bounded worker boundary."""
        return service.cancel(job_id)

    @mcp.tool()
    def cfd_list_topology_roles() -> list:
        """List persistent topology roles in this configured CAD revision."""
        return topology.list_topology_roles()

    @mcp.tool()
    def cfd_resolve_role_to_faces(selection_id: str, allow_set: bool = False) -> dict:
        """Resolve persistent named faces; reject ambiguous/heuristic selections."""
        from .models import SurfaceRef

        return topology.resolve_role_to_faces(
            SurfaceRef(
                source="selection",
                key=selection_id,
                cardinality="set_allowed" if allow_set else "exact_one",
            )
        ).model_dump(mode="json")

    @mcp.tool()
    def cfd_export_topology_face_map(selection_ids: list[str]) -> dict:
        """Export an auditable map of named selections."""
        from .models import SurfaceRef

        return topology.export_topology_face_map(
            [SurfaceRef(source="selection", key=s) for s in selection_ids]
        )

    @mcp.tool()
    def cfd_resume(job_id: str) -> dict:
        """Resume a durable CFD checkpoint with unchanged original spec/backend."""
        return service.resume(job_id)

    @mcp.tool()
    def cfd_check_role_binding_stable(
        old_revision: str, new_revision: str, selection_id: str
    ) -> dict:
        """Re-solve a selection against two operator-configured revision bridges."""
        from .models import CFDError, SurfaceRef
        from .topology import check_role_binding_stable

        if (
            not revisions
            or old_revision not in revisions
            or new_revision not in revisions
        ):
            raise CFDError(
                "revision_not_configured",
                "Both revision bridges must be configured",
                "topology",
                "capability_gap",
            )
        return check_role_binding_stable(
            revisions[old_revision],
            revisions[new_revision],
            SurfaceRef(source="selection", key=selection_id),
        )
