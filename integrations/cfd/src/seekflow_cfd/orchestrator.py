"""Deterministic state machine coordinating bounded expert decisions and tools."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from .agents import RepairProposal, apply_repair
from .backends import OPERATIONS
from .evidence import (
    DomainReport,
    MeshReport,
    ResultReport,
    Sample,
    SolverReport,
    check_domain,
    check_mesh,
    check_results,
    convergence,
)
from .models import CFDError, SimulationSpec, digest
from .storage import JobStore, confined, now
from .topology import verify_geometry


class CFDOrchestrator:
    def __init__(
        self,
        output_root: Path,
        input_root: Path,
        backend,
        topology_factory,
        experts=None,
    ):
        self.output_root = Path(output_root)
        self.input_root = Path(input_root).resolve()
        self.backend = backend
        self.topology_factory = topology_factory
        self.experts = experts
        from .tools import ToolRegistry

        self.tools = ToolRegistry(backend)

    def run(self, spec: SimulationSpec, *, job_id=None, resume=False, pause_after=None):
        spec = SimulationSpec.model_validate(spec.model_dump(mode="json"))
        store = JobStore(self.output_root, job_id or uuid.uuid4().hex)
        with store.lock():
            return self._run_locked(store, spec, resume, pause_after)

    def _run_locked(self, store, original, resume, pause_after):
        started = time.monotonic()
        state_path = store.path / "state.json"
        if resume:
            if not state_path.exists():
                raise CFDError(
                    "checkpoint_missing", "No checkpoint to resume", "resume"
                )
            store.verify_events()
            store.verify_manifest()
            state = store.read("state.json")
            if state["original_spec_hash"] != original.spec_hash or state[
                "backend"
            ] != self.backend.capabilities.model_dump(mode="json"):
                raise CFDError(
                    "resume_mismatch",
                    "Spec or backend changed; start a new replay job",
                    "resume",
                )
            if state.get("terminal"):
                return store.read("record.json")
        else:
            if state_path.exists() or store.events():
                raise CFDError("job_exists", "Use resume or a new job id", "storage")
            state = {
                "record_id": "cfd-" + store.job_id,
                "original_spec_hash": original.spec_hash,
                "spec": original.model_dump(mode="json"),
                "backend": self.backend.capabilities.model_dump(mode="json"),
                "stage": "preflight",
                "tool_count": 0,
                "repairs": 0,
                "total_iterations": 0,
                "elapsed_s": 0,
                "samples": [],
                "agent_trace": [],
                "collected_at": now(),
                "terminal": False,
            }
            store.write("original_spec.json", original)
        if resume and self.experts:
            self.experts.trace = list(state["agent_trace"])
        previous_elapsed = state["elapsed_s"]
        spec = SimulationSpec.model_validate(state["spec"])
        topology = None
        status = "failed"
        diagnostic = None
        warnings = []
        terminal = True

        def checkpoint():
            state["elapsed_s"] = previous_elapsed + time.monotonic() - started
            state["spec"] = spec.model_dump(mode="json")
            store.write("state.json", state)
            store.write("manifest.json", store.manifest(spec.budget.max_output_bytes))

        def remaining():
            seconds = (
                spec.budget.wall_time_s
                - previous_elapsed
                - (time.monotonic() - started)
            )
            if seconds <= 0:
                raise CFDError(
                    "task_timeout",
                    "Task wall-time budget exhausted",
                    state["stage"],
                    "timeout",
                )
            if (store.path / "cancel.request").exists():
                raise CFDError(
                    "cancelled", "Operator cancelled job", state["stage"], "rejected"
                )
            return seconds

        def call(name, **kwargs):
            seconds = remaining()
            if state["tool_count"] >= spec.budget.max_tool_calls:
                raise CFDError(
                    "tool_budget",
                    "Tool call budget exhausted",
                    state["stage"],
                    "failed",
                )
            state["tool_count"] += 1
            payload = {"spec": spec.model_dump(mode="json"), **kwargs}
            call_id = uuid.uuid4().hex
            event = {
                "type": "tool_call",
                "call_id": call_id,
                "tool_name": name,
                "tool_version": self.backend.capabilities.version,
                "agent": OPERATIONS[name],
                "spec_node": state["stage"],
                "spec_hash": spec.spec_hash,
                "input_hash": digest(payload),
                "started_at": now(),
            }
            state["in_flight"] = call_id
            store.event({**event, "status": "started"})
            checkpoint()
            t = time.monotonic()
            try:
                output = self.tools.invoke(
                    name, OPERATIONS[name], payload, store.path, seconds
                )
                # Validate JSON serializability before committing a tool result.
                output_hash = digest(output)
                store.write(
                    "calls/" + call_id + ".json", {"input": payload, "output": output}
                )
                remaining()
                store.event(
                    {
                        **event,
                        "status": "success",
                        "finished_at": now(),
                        "duration_s": time.monotonic() - t,
                        "output_hash": output_hash,
                    }
                )
                state["in_flight"] = None
                return output
            except Exception as exc:
                store.event(
                    {
                        **event,
                        "status": "failed",
                        "finished_at": now(),
                        "duration_s": time.monotonic() - t,
                        "error": str(exc),
                        "diagnostic": exc.diagnostic.model_dump(mode="json")
                        if isinstance(exc, CFDError)
                        else None,
                    }
                )
                state["in_flight"] = None
                raise

        def artifacts(paths):
            for name in paths:
                if not confined(store.path, name).is_file():
                    raise CFDError(
                        "missing_artifact",
                        "Missing backend artifact: " + name,
                        state["stage"],
                        "failed",
                    )

        def acknowledgement(data):
            if data.get("ok") is not True or data.get("spec_hash") != spec.spec_hash:
                raise CFDError(
                    "backend_ack",
                    "Backend did not acknowledge this exact spec",
                    state["stage"],
                    "failed",
                )

        try:
            if state.get("in_flight"):
                raise CFDError(
                    "uncertain_external_state",
                    "Interrupted external call requires local reconciliation and a new job; it is never blindly retried",
                    "resume",
                    "capability_gap",
                )
            if not spec.expert_confirmed:
                raise CFDError(
                    "needs_expert_confirmation",
                    "Confirm task semantics and hard parameters in the spec before execution",
                    "preflight",
                )
            self.backend.capabilities.check(spec)
            if not self.backend.capabilities.is_mock:
                verify_geometry(self.input_root, spec.geometry_ref)
            topology = self.topology_factory(spec.geometry_ref)
            if bool(topology.is_mock) != self.backend.capabilities.is_mock:
                raise CFDError(
                    "mock_real_mismatch",
                    "Mock topology and real solver cannot be mixed",
                    "preflight",
                )
            if (
                resume
                and state.get("samples")
                and not self.backend.capabilities.restart
            ):
                raise CFDError(
                    "restart_unsupported",
                    "Backend has no verified restart support",
                    "resume",
                    "capability_gap",
                )
            if self.experts and not state["agent_trace"]:
                try:
                    state["agent_trace"] = self.experts.review(spec)
                finally:
                    state["agent_trace"] = list(self.experts.trace)
            if state["stage"] == "preflight":
                state["stage"] = "topology"
            while True:
                remaining()
                try:
                    stage = state["stage"]
                    if stage == "topology":
                        surfaces = {
                            b.surface.key: b.surface
                            for b in spec.boundary_specs
                            if b.surface.source == "selection"
                        }
                        surfaces.update(
                            {
                                r.surface.key: r.surface
                                for r in spec.mesh_strategy.refinements
                                if r.surface.source == "selection"
                            }
                        )
                        if hasattr(topology, "prepare"):
                            topology.prepare(
                                list(surfaces.values()),
                                store.path,
                                remaining(),
                                spec.budget,
                            )
                        state["topology"] = {}
                        for key, surface in surfaces.items():
                            if state["tool_count"] >= spec.budget.max_tool_calls:
                                raise CFDError(
                                    "tool_budget",
                                    "Topology tool budget exhausted",
                                    "topology",
                                    "failed",
                                )
                            state["tool_count"] += 1
                            t = time.monotonic()
                            try:
                                binding = topology.resolve_role_to_faces(surface)
                                artifacts(binding.native_face_artifacts.values())
                                state["topology"][key] = binding.model_dump(mode="json")
                                store.event(
                                    {
                                        "type": "tool_call",
                                        "tool_name": "topology.resolve_role_to_faces",
                                        "tool_version": "1",
                                        "agent": "geometry_topology",
                                        "spec_node": "boundary_specs",
                                        "input_hash": digest(surface),
                                        "output_hash": digest(binding),
                                        "status": "success",
                                        "duration_s": time.monotonic() - t,
                                    }
                                )
                            except Exception as exc:
                                store.event(
                                    {
                                        "type": "tool_call",
                                        "tool_name": "topology.resolve_role_to_faces",
                                        "tool_version": "1",
                                        "agent": "geometry_topology",
                                        "spec_node": "boundary_specs",
                                        "input_hash": digest(surface),
                                        "status": "failed",
                                        "error": str(exc),
                                        "duration_s": time.monotonic() - t,
                                    }
                                )
                                raise
                        store.write("topology_face_map.json", state["topology"])
                        state["stage"] = "domain"
                    elif stage == "domain":
                        report = DomainReport.model_validate(
                            call("domain.construct", topology=state["topology"])
                        )
                        check_domain(spec, report)
                        for b in spec.boundary_specs:
                            if b.surface.source == "selection":
                                before = set(
                                    state["topology"][b.surface.key]["entity_ids"]
                                )
                                after = report.boundary_map[b.name]
                                if (
                                    set(after.entity_ids) != before
                                    and set(after.parent_entity_ids) != before
                                ):
                                    raise CFDError(
                                        "domain_history",
                                        "Changed faces require exact source-to-domain history",
                                        "domain",
                                    )
                        state["domain"] = report.model_dump(mode="json")
                        store.write("domain_report.json", report)
                        state["stage"] = "mesh"
                    elif stage == "mesh":
                        report = MeshReport.model_validate(
                            call(
                                "mesh.generate",
                                domain=state["domain"],
                                topology=state["topology"],
                            )
                        )
                        store.write(
                            f"attempts/{state['repairs']}/mesh_report.json", report
                        )
                        check_mesh(
                            spec, DomainReport.model_validate(state["domain"]), report
                        )
                        artifacts(report.artifact_paths)
                        state["mesh"] = report.model_dump(mode="json")
                        store.write("mesh_report.json", report)
                        state["stage"] = "physics"
                    elif stage == "physics":
                        acknowledgement(
                            call(
                                "physics.configure",
                                domain=state["domain"],
                                mesh=state["mesh"],
                            )
                        )
                        state["stage"] = "initialize"
                    elif stage == "initialize":
                        acknowledgement(call("solver.initialize", mesh=state["mesh"]))
                        state["stage"] = "solver"
                    elif stage == "solver":
                        count = min(
                            spec.solver_control.chunk_iterations,
                            spec.solver_control.max_iterations
                            - state["total_iterations"],
                        )
                        if count <= 0:
                            raise CFDError(
                                "iteration_budget",
                                "Iteration budget exhausted without convergence",
                                "solver",
                                "failed",
                            )
                        start = (
                            state["samples"][-1]["iteration"] if state["samples"] else 0
                        )
                        state["total_iterations"] += count
                        report = SolverReport.model_validate(
                            call(
                                "solver.advance",
                                start_iteration=start,
                                iterations=count,
                                checkpoint=state.get("solver_checkpoint"),
                                mesh=state["mesh"],
                            )
                        )
                        if (
                            report.spec_hash != spec.spec_hash
                            or report.samples[0].iteration <= start
                            or report.samples[-1].iteration > start + count
                        ):
                            raise CFDError(
                                "solver_iteration_contract",
                                "Solver response violates spec/iteration limits",
                                "solver",
                                "failed",
                            )
                        artifacts([report.checkpoint, *report.log_paths])
                        if report.solver_error:
                            raise CFDError(
                                "solver_error",
                                report.solver_error,
                                "solver",
                                "failed",
                                True,
                            )
                        state["samples"].extend(
                            s.model_dump(mode="json") for s in report.samples
                        )
                        state["solver_checkpoint"] = report.checkpoint
                        state.setdefault("solver_logs", []).extend(report.log_paths)
                        verdict = convergence(
                            spec, [Sample.model_validate(s) for s in state["samples"]]
                        )
                        state["convergence"] = verdict
                        store.write("convergence.json", verdict)
                        if verdict["state"] in {"diverged", "stagnated"}:
                            raise CFDError(
                                verdict["state"],
                                "Solver failed independent convergence checks",
                                "solver",
                                "failed",
                                True,
                            )
                        if verdict["state"] == "converged":
                            acknowledgement(
                                call(
                                    "solver.stop", checkpoint=state["solver_checkpoint"]
                                )
                            )
                            state["stage"] = "postprocess"
                    elif stage == "postprocess":
                        report = ResultReport.model_validate(
                            call(
                                "results.extract",
                                mesh=state["mesh"],
                                checkpoint=state["solver_checkpoint"],
                            )
                        )
                        warnings = check_results(spec, report)
                        artifacts(report.artifact_paths)
                        if self.experts:
                            if len(self.experts.trace) >= spec.budget.max_agent_calls:
                                raise CFDError(
                                    "agent_budget",
                                    "Result-review agent budget exhausted",
                                    "postprocess",
                                    "failed",
                                )
                            last_sample = (
                                state["samples"][-1] if state["samples"] else {}
                            )
                            mass_flux = last_sample.get("mass_flux_kg_s", {})
                            flux_scale = max(
                                sum(abs(v) for v in mass_flux.values()), 1e-30
                            )
                            review_evidence = {
                                "result_report": report.model_dump(mode="json"),
                                "mesh_report": state["mesh"],
                                "latest_sample": last_sample,
                                "boundary_flux_summary": {
                                    "boundary_mass_flux_kg_s": mass_flux,
                                    "net_mass_flux_kg_s": sum(mass_flux.values()),
                                    "relative_mass_imbalance": (
                                        abs(sum(mass_flux.values())) / flux_scale
                                    ),
                                },
                                "energy_equation_active": (
                                    spec.physics_spec.heat_transfer != "isothermal"
                                ),
                            }
                            review = self.experts.review_results(
                                spec,
                                review_evidence,
                                state["convergence"],
                            )
                            state["agent_trace"] = list(self.experts.trace)
                            if review.decision != "accept":
                                warnings.append(
                                    "Expert review required: " + review.rationale
                                )
                        state["results"] = report.model_dump(mode="json")
                        state["warnings"] = warnings
                        store.write("results.json", report)
                        state["stage"] = "complete"
                    elif stage == "complete":
                        status = "success"
                        break
                    else:
                        raise CFDError(
                            "invalid_checkpoint",
                            "Unknown checkpoint stage",
                            "resume",
                            "failed",
                        )
                    checkpoint()
                    if pause_after == stage:
                        status, terminal = "paused", False
                        break
                except CFDError as exc:
                    if (
                        not exc.diagnostic.recoverable
                        or state["repairs"] >= spec.budget.max_repairs
                    ):
                        raise
                    action = (
                        "refine_mesh"
                        if exc.diagnostic.stage == "mesh"
                        else "reduce_relaxation"
                    )
                    if action not in spec.allowed_repairs:
                        raise
                    proposal = RepairProposal(
                        action=action,
                        factor=0.5,
                        rationale="Bounded repair explicitly allowed by spec",
                    )
                    if self.experts:
                        if len(self.experts.trace) >= spec.budget.max_agent_calls:
                            raise CFDError(
                                "agent_budget",
                                "Repair agent budget exhausted",
                                "repair",
                                "failed",
                            )
                        proposal = self.experts.repair(spec, exc.diagnostic)
                        state["agent_trace"] = list(self.experts.trace)
                    if proposal.action not in spec.allowed_repairs:
                        raise CFDError(
                            "repair_not_allowed",
                            "Repair violates operator allowlist",
                            "repair",
                        )
                    repaired = apply_repair(spec, proposal, exc.diagnostic.stage)
                    state["repairs"] += 1
                    store.write(
                        f"attempts/{state['repairs']}/previous_state.json", state
                    )
                    store.event(
                        {
                            "type": "repair",
                            "diagnostic": exc.diagnostic.model_dump(mode="json"),
                            "proposal": proposal.model_dump(mode="json"),
                            "old_spec_hash": spec.spec_hash,
                            "new_spec_hash": repaired.spec_hash,
                        }
                    )
                    spec = repaired
                    state.update(stage="domain", samples=[])
                    for key in (
                        "domain",
                        "mesh",
                        "solver_checkpoint",
                        "results",
                        "convergence",
                    ):
                        state.pop(key, None)
                    checkpoint()
        except CFDError as exc:
            diagnostic = exc.diagnostic.model_dump(mode="json")
            status = exc.diagnostic.status
        except Exception as exc:  # noqa: BLE001 -- durable job failure boundary
            diagnostic = {
                "code": "unexpected_error",
                "message": str(exc),
                "stage": state["stage"],
                "status": "failed",
                "recoverable": False,
            }
            status = "failed"
        finally:
            if topology is not None and hasattr(topology, "close"):
                topology.close()
        state["terminal"] = terminal
        state["elapsed_s"] = previous_elapsed + time.monotonic() - started
        warnings = state.get("warnings", warnings)
        if self.backend.capabilities.is_mock:
            warnings = [
                *warnings,
                "MOCK: synthetic pipeline evidence; not a physical CFD result",
            ]
        record = {
            "record_id": state["record_id"],
            "schema_version": "cfd_sim_v1",
            "collected_at": state["collected_at"],
            "cad_revision_id": spec.geometry_ref.revision_id,
            "cad_record_id": spec.geometry_ref.cad_record_id,
            "simulation_spec_hash": spec.spec_hash,
            "original_spec_hash": original.spec_hash,
            "simulation_spec": spec.model_dump(mode="json"),
            "is_mock": self.backend.capabilities.is_mock,
            "agent_trace": state["agent_trace"],
            "tool_calls": [e for e in store.events() if e.get("type") == "tool_call"],
            "mesh_report": state.get("mesh", {}),
            "solver_log_summary": {
                "logs": state.get("solver_logs", []),
                "convergence": state.get("convergence", {}),
                "total_iterations": state["total_iterations"],
            },
            "metrics": state.get("results", {}).get("metrics", {})
            if status == "success"
            else {},
            "status": status,
            "error_stage": diagnostic["stage"] if diagnostic else None,
            "error_message": diagnostic["message"] if diagnostic else None,
            "diagnostic": diagnostic,
            "elapsed_s": state["elapsed_s"],
            "warnings": warnings,
            "requires_manual_review": bool(warnings),
            "mesh_independence": {
                "verified": False,
                "reason": "separate multi-mesh study required",
            },
        }
        store.write("record.json", record)
        store.write("simulation_spec.json", spec)
        from .reporting import write_report

        write_report(store.path, record, state.get("samples", []))
        try:
            checkpoint()
        except CFDError as exc:
            record.update(
                status=exc.diagnostic.status,
                metrics={},
                diagnostic=exc.diagnostic.model_dump(mode="json"),
                error_stage=exc.diagnostic.stage,
                error_message=exc.diagnostic.message,
            )
            store.write("record.json", record)
            store.write(
                "manifest.json",
                {
                    "files": {},
                    "verification_error": exc.diagnostic.model_dump(mode="json"),
                },
            )
        return record
