"""File RPC adapter for operator-installed Ansys/CFX/OpenFOAM workers."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from .backends import OPERATIONS, Capabilities
from .models import CFDError, SimulationSpec, digest
from .process import run_worker
from .storage import atomic_json, confined


class LocalWorkerBackend:
    """One bounded worker invocation per generic operation.

    The worker receives request and response filenames as its final two argv
    arguments. It must persist solver state between chunks and exit without
    leaving daemons. `command` and capabilities are operator configuration only.
    Use a custom supervisor with Windows Job Objects for native Windows Ansys.
    """

    def __init__(
        self,
        command: list[str],
        capabilities: Capabilities,
        supervisor=run_worker,
        input_root=None,
    ):
        if capabilities.is_mock:
            raise ValueError("Local solver capabilities cannot claim mock mode")
        self.command = tuple(command)
        self.capabilities = capabilities
        self.supervisor = supervisor
        self.input_root = Path(input_root).resolve() if input_root is not None else None

    def execute(self, operation, payload, job_dir, timeout_s):
        if operation not in OPERATIONS or operation not in self.capabilities.operations:
            raise CFDError(
                "unsupported_operation", operation, "tools", "capability_gap"
            )
        spec = SimulationSpec.model_validate(payload["spec"])
        call_id = uuid.uuid4().hex
        request = {
            "protocol": "cfd_worker_v1",
            "call_id": call_id,
            "operation": operation,
            "input_hash": digest(payload),
            "payload": payload,
        }
        if self.input_root is not None:
            request["input_root"] = str(self.input_root)
        input_name, output_name = (
            f"rpc-{call_id}.request.json",
            f"rpc-{call_id}.response.json",
        )
        atomic_json(job_dir / input_name, request)
        b = spec.budget
        self.supervisor(
            [*self.command, input_name, output_name],
            job_dir,
            timeout_s,
            b.cpu_count,
            b.memory_mb,
            b.max_output_bytes,
            "rpc-" + call_id,
        )
        output = confined(job_dir, output_name)
        if not output.is_file() or output.stat().st_size > min(
            b.max_output_bytes, 16_000_000
        ):
            raise CFDError(
                "worker_protocol",
                "Missing or oversized worker response",
                "runner",
                "failed",
            )
        data = json.loads(output.read_text(encoding="utf-8"))
        if (
            data.get("call_id") != call_id
            or data.get("input_hash") != request["input_hash"]
            or data.get("protocol") != "cfd_worker_v1"
        ):
            raise CFDError(
                "worker_protocol",
                "Worker response identity mismatch",
                "runner",
                "failed",
            )
        if data.get("error"):
            error = data["error"]
            raise CFDError(
                error["code"],
                error["message"],
                operation,
                error.get("status", "failed"),
            )
        if not isinstance(data.get("result"), dict):
            raise CFDError(
                "worker_protocol",
                "Worker must return a result object",
                "runner",
                "failed",
            )
        return data["result"]
