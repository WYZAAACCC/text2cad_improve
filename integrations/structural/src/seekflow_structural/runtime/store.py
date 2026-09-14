"""Job-local atomic checkpoints, integrity manifests and append-only audit events.

A copy, not an import, of the equivalent module in `seekflow_cfd`. The logic is
pure standard library and has nothing to do with CFD, but reaching it through
that package would pull the whole CFD package in (`seekflow_cfd/__init__.py`
imports its models and orchestrator) for what is a lock file and a hash chain.
The two copies must not drift in behaviour; the tests here pin the behaviours
that matter - path confinement, atomic replace, and the audit chain.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from seekflow_structural.errors import (
    STATUS_FAILED,
    StructuralError,
)
from seekflow_structural.serialize import canonical, digest

JOB_ID_ALPHABET = (
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def confined(root: Path, relative: str) -> Path:
    """Resolve a job-relative path, refusing anything that could escape.

    Every artifact this chain writes is named relative to its job directory.
    Absolute paths, `..`, backslashes and drive colons are all refused rather
    than normalised: a path that needs normalising to be safe is a path that
    was written by something that did not know where it was writing.
    """
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts or "\\" in relative or ":" in relative:
        raise StructuralError(
            "unsafe_path", "Expected a job-relative artifact path", "storage"
        )
    result = (root / p).resolve()
    if not result.is_relative_to(root.resolve()):
        raise StructuralError(
            "unsafe_path", "Artifact escapes workspace", "storage"
        )
    return result


def atomic_json(path: Path, value) -> None:
    """Write via a temporary file and rename, so a crash cannot truncate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as f:
            f.write(canonical(value))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class JobStore:
    def __init__(self, root: Path, job_id: str):
        if not job_id or any(c not in JOB_ID_ALPHABET for c in job_id):
            raise StructuralError("invalid_job_id", "Invalid job id", "storage")
        self.root = Path(root).resolve()
        self.path = confined(self.root, "jobs/" + job_id)
        self.path.mkdir(parents=True, exist_ok=True)
        self.job_id = job_id

    @contextmanager
    def lock(self):
        """An OS-released lock, so a crashed worker cannot leave a stale one."""
        lock = self.path / "job.lock"
        with lock.open("a+b") as f:
            if os.name == "nt":
                import msvcrt

                f.seek(0)
                if not f.read(1):
                    f.write(b"0")
                    f.flush()
                f.seek(0)
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise StructuralError(
                        "job_busy", "Job is already running", "storage"
                    ) from exc
            else:
                import fcntl

                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise StructuralError(
                        "job_busy", "Job is already running", "storage"
                    ) from exc
            try:
                yield
            finally:
                if os.name == "nt":
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def write(self, name, data) -> None:
        atomic_json(confined(self.path, name), data)

    def read(self, name):
        return json.loads(confined(self.path, name).read_text(encoding="utf-8"))

    def exists(self, name) -> bool:
        return confined(self.path, name).is_file()

    def events(self) -> list[dict]:
        p = self.path / "events.jsonl"
        if not p.exists():
            return []
        return [
            json.loads(line)
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def event(self, event: dict) -> dict:
        """Append one audit event, chained to the hash of the previous one.

        The chain is what makes the log tamper-evident: removing or editing an
        event breaks every hash after it.
        """
        previous = self.events()
        payload = {
            "sequence": len(previous),
            "timestamp": now(),
            "previous_hash": previous[-1]["event_hash"] if previous else None,
            **event,
        }
        payload["event_hash"] = digest(payload)
        with (self.path / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(canonical(payload) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return payload

    def verify_events(self) -> None:
        previous = None
        for i, event in enumerate(self.events()):
            payload = dict(event)
            expected = payload.pop("event_hash")
            if (
                payload["sequence"] != i
                or payload["previous_hash"] != previous
                or digest(payload) != expected
            ):
                raise StructuralError(
                    "audit_corrupt", "Audit hash chain failed", "storage"
                )
            previous = expected

    def manifest(self, max_bytes: int) -> dict:
        """Hash every artifact, and refuse to run past the output budget."""
        files = {}
        total = 0
        for p in self.path.rglob("*"):
            if p.is_symlink():
                raise StructuralError(
                    "unsafe_output", "Symlink in job output", "storage"
                )
            if p.is_file() and p.name not in {"job.lock", "manifest.json"}:
                total += p.stat().st_size
                files[p.relative_to(self.path).as_posix()] = file_hash(p)
        if total > max_bytes:
            raise StructuralError(
                "output_budget",
                "Job output exceeds byte budget",
                "storage",
                status=STATUS_FAILED,
            )
        return {"files": files, "total_bytes": total}

    def verify_manifest(self) -> None:
        manifest = self.read("manifest.json")
        if manifest.get("verification_error"):
            raise StructuralError(
                "manifest_invalid",
                "Job output integrity could not be verified",
                "storage",
            )
        for name, expected in manifest["files"].items():
            p = confined(self.path, name)
            if not p.is_file() or file_hash(p) != expected:
                raise StructuralError(
                    "artifact_changed",
                    f"Artifact missing or modified: {name}",
                    "storage",
                )
