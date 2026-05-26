"""NX job queue tests (no NXOpen required)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from seekflow_engineering_tools.nx.job_queue import NXJobQueue


class TestNXJobQueue:
    def test_submit_creates_job_file(self, tmp_path: Path):
        q = NXJobQueue(tmp_path)
        job_id = q.submit("create_block_part", {"length_mm": 100})

        job_file = q.pending_dir / f"{job_id}.json"
        assert job_file.exists()

        data = json.loads(job_file.read_text())
        assert data["action"] == "create_block_part"
        assert data["params"]["length_mm"] == 100

    def test_wait_returns_done_result(self, tmp_path: Path):
        q = NXJobQueue(tmp_path)
        job_id = q.submit("create_block_part", {})

        # Simulate NX bridge processing
        result = {
            "job_id": job_id,
            "ok": True,
            "message": "done",
            "files_created": ["/ws/block.prt"],
            "metrics": {},
            "error": None,
        }
        result_path = q.done_dir / f"{job_id}.result.json"
        result_path.write_text(json.dumps(result))

        got = q.wait(job_id, timeout_s=5)
        assert got["ok"] is True
        assert got["files_created"] == ["/ws/block.prt"]

    def test_wait_returns_failed_result(self, tmp_path: Path):
        q = NXJobQueue(tmp_path)
        job_id = q.submit("create_block_part", {})

        result = {
            "job_id": job_id,
            "ok": False,
            "message": "fail",
            "files_created": [],
            "metrics": {},
            "error": "NXOpen error",
        }
        (q.failed_dir / f"{job_id}.result.json").write_text(json.dumps(result))

        got = q.wait(job_id, timeout_s=5)
        assert got["ok"] is False
        assert got["error"] == "NXOpen error"

    def test_wait_timeout(self, tmp_path: Path):
        q = NXJobQueue(tmp_path)
        job_id = q.submit("create_block_part", {})

        with pytest.raises(TimeoutError):
            q.wait(job_id, timeout_s=0.5)

    def test_queue_status(self, tmp_path: Path):
        q = NXJobQueue(tmp_path)
        q.submit("create_block_part", {})
        q.submit("create_block_with_hole", {"length_mm": 10, "width_mm": 10, "height_mm": 10, "hole_dia_mm": 5, "out_prt": "test.prt"})

        status = q.queue_status()
        assert status["pending"] == 2
        assert status["done"] == 0

    def test_multiple_jobs_independent(self, tmp_path: Path):
        q = NXJobQueue(tmp_path)
        id1 = q.submit("create_block_part", {"n": 1})
        id2 = q.submit("create_l_bracket", {"n": 2})

        (q.done_dir / f"{id1}.result.json").write_text(
            json.dumps({"job_id": id1, "ok": True})
        )
        (q.done_dir / f"{id2}.result.json").write_text(
            json.dumps({"job_id": id2, "ok": False, "error": "boom"})
        )

        r1 = q.wait(id1, timeout_s=5)
        r2 = q.wait(id2, timeout_s=5)

        assert r1["ok"] is True
        assert r2["ok"] is False
