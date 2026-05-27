"""File-queue bridge for NX 12.0 — the safe NXOpen integration path.

Problem:
  NXOpen Python requires a running NX session. You cannot simply
  ``python create_part.py`` and expect NXOpen to be available.

Solution:
  This module writes job files to a queue directory. A long-running
  journal inside NX (``nx_bridge_bootstrap.py``) picks them up,
  executes via NXOpen, and writes result files back.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

ALLOWED_ACTIONS: set[str] = {
    "create_block_part",
    "create_block_with_hole",
    "create_l_bracket",
    "create_stepped_block",
    "export_step",
    "import_step_as_prt",
}


class NXJobQueue:
    """File-based job queue for communicating with NX bridge."""

    def __init__(self, job_root: Path):
        self.job_root = Path(job_root)
        self.pending_dir = self.job_root / "pending"
        self.running_dir = self.job_root / "running"
        self.done_dir = self.job_root / "done"
        self.failed_dir = self.job_root / "failed"

        for d in [
            self.pending_dir,
            self.running_dir,
            self.done_dir,
            self.failed_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def heartbeat_path(self) -> Path:
        """Path to the bridge heartbeat file."""
        return self.running_dir / "heartbeat.json"

    def bridge_status(self, stale_after_s: float = 15.0) -> dict:
        """Read heartbeat and report whether the NX bridge is alive."""
        hp = self.heartbeat_path
        if not hp.exists():
            return {"bridge_running": False, "reason": "heartbeat_missing"}
        try:
            data = json.loads(hp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"bridge_running": False, "reason": "heartbeat_unreadable"}
        age_s = time.time() - float(data.get("time_epoch", 0))
        return {
            "bridge_running": age_s <= stale_after_s,
            "heartbeat_age_s": round(age_s, 3),
            "heartbeat": data,
        }

    # ── submit ──────────────────────────────────────────────────────

    def submit(self, action: str, params: dict) -> str:
        """Write a job to the pending directory. Returns *job_id*.

        Raises ValueError if *action* is not in ALLOWED_ACTIONS.
        """
        if action not in ALLOWED_ACTIONS:
            raise ValueError(
                f"Unknown NX action '{action}'. Allowed: {sorted(ALLOWED_ACTIONS)}"
            )

        job_id = uuid.uuid4().hex
        job = {
            "job_id": job_id,
            "action": action,
            "params": params,
            "created_at": time.time(),
        }
        job_path = self.pending_dir / f"{job_id}.json"
        job_path.write_text(
            json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return job_id

    # ── wait ────────────────────────────────────────────────────────

    def wait(self, job_id: str, timeout_s: float) -> dict:
        """Block until the job completes or *timeout_s* elapses."""
        done_path = self.done_dir / f"{job_id}.result.json"
        failed_path = self.failed_dir / f"{job_id}.result.json"

        deadline = time.time() + timeout_s

        while time.time() < deadline:
            if done_path.exists():
                return json.loads(done_path.read_text(encoding="utf-8"))

            if failed_path.exists():
                return json.loads(failed_path.read_text(encoding="utf-8"))

            time.sleep(1.0)

        raise TimeoutError(
            f"NX job {job_id} timed out after {timeout_s} seconds."
        )

    # ── status ──────────────────────────────────────────────────────

    def pending_count(self) -> int:
        return len(list(self.pending_dir.glob("*.json")))

    def queue_status(self) -> dict:
        return {
            "pending": len(list(self.pending_dir.glob("*.json"))),
            "running": len(list(self.running_dir.glob("*.json"))),
            "done": len(list(self.done_dir.glob("*.result.json"))),
            "failed": len(list(self.failed_dir.glob("*.result.json"))),
        }
