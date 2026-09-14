"""Job-local atomic checkpoints, integrity manifests and append-only audit events."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import CFDError, canonical, digest


def now():
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def confined(root: Path, relative: str) -> Path:
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts or "\\" in relative or ":" in relative:
        raise CFDError(
            "unsafe_path", "Expected a job-relative artifact path", "storage"
        )
    result = (root / p).resolve()
    if not result.is_relative_to(root.resolve()):
        raise CFDError("unsafe_path", "Artifact escapes workspace", "storage")
    return result


def atomic_json(path: Path, value):
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
        if not job_id or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for c in job_id
        ):
            raise CFDError("invalid_job_id", "Invalid job id", "storage")
        self.root = Path(root).resolve()
        self.path = confined(self.root, "jobs/" + job_id)
        self.path.mkdir(parents=True, exist_ok=True)
        self.job_id = job_id

    @contextmanager
    def lock(self):
        """OS-released lock survives worker crash without stale lock deletion."""
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
                    raise CFDError(
                        "job_busy", "Job is already running", "storage"
                    ) from exc
            else:
                import fcntl

                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise CFDError(
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

    def write(self, name, data):
        atomic_json(confined(self.path, name), data)

    def read(self, name):
        return json.loads(confined(self.path, name).read_text(encoding="utf-8"))

    def events(self):
        p = self.path / "events.jsonl"
        return (
            [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
            if p.exists()
            else []
        )

    def event(self, event):
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

    def verify_events(self):
        previous = None
        for i, event in enumerate(self.events()):
            payload = dict(event)
            expected = payload.pop("event_hash")
            if (
                payload["sequence"] != i
                or payload["previous_hash"] != previous
                or digest(payload) != expected
            ):
                raise CFDError("audit_corrupt", "Audit hash chain failed", "storage")
            previous = expected

    def manifest(self, max_bytes: int):
        files = {}
        total = 0
        for p in self.path.rglob("*"):
            if p.is_symlink():
                raise CFDError("unsafe_output", "Symlink in job output", "storage")
            if p.is_file() and p.name not in {"job.lock", "manifest.json"}:
                total += p.stat().st_size
                files[p.relative_to(self.path).as_posix()] = file_hash(p)
        if total > max_bytes:
            raise CFDError(
                "output_budget", "Job output exceeds byte budget", "storage", "failed"
            )
        return {"files": files, "total_bytes": total}

    def verify_manifest(self):
        manifest = self.read("manifest.json")
        if manifest.get("verification_error"):
            raise CFDError(
                "manifest_invalid",
                "Job output integrity could not be verified",
                "storage",
            )
        for name, expected in manifest["files"].items():
            p = confined(self.path, name)
            if not p.is_file() or file_hash(p) != expected:
                raise CFDError(
                    "artifact_changed",
                    f"Artifact missing or modified: {name}",
                    "storage",
                )
