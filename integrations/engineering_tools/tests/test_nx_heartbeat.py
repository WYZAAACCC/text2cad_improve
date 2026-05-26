"""Test NX bridge heartbeat mechanism."""

from __future__ import annotations

import json
import time
from pathlib import Path

from seekflow_engineering_tools.nx.job_queue import NXJobQueue


class TestNXHeartbeat:
    def test_bridge_status_missing_heartbeat(self, tmp_path: Path):
        q = NXJobQueue(tmp_path)
        status = q.bridge_status(stale_after_s=15.0)
        assert status["bridge_running"] is False
        assert status["reason"] == "heartbeat_missing"

    def test_bridge_status_valid_heartbeat(self, tmp_path: Path):
        q = NXJobQueue(tmp_path)
        hp = q.heartbeat_path
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(json.dumps({
            "time_epoch": time.time(),
            "time_iso": "2025-01-01T00:00:00",
            "nx_version": "12.0",
        }))
        status = q.bridge_status(stale_after_s=15.0)
        assert status["bridge_running"] is True
        assert status["heartbeat_age_s"] < 5.0

    def test_bridge_status_stale_heartbeat(self, tmp_path: Path):
        q = NXJobQueue(tmp_path)
        hp = q.heartbeat_path
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(json.dumps({
            "time_epoch": time.time() - 30.0,
            "time_iso": "2025-01-01T00:00:00",
            "nx_version": "12.0",
        }))
        status = q.bridge_status(stale_after_s=15.0)
        assert status["bridge_running"] is False

    def test_bridge_status_unreadable_heartbeat(self, tmp_path: Path):
        q = NXJobQueue(tmp_path)
        hp = q.heartbeat_path
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text("not valid json{{{")
        status = q.bridge_status(stale_after_s=15.0)
        assert status["bridge_running"] is False
        assert status["reason"] == "heartbeat_unreadable"

    def test_submit_rejects_unknown_action(self, tmp_path: Path):
        q = NXJobQueue(tmp_path)
        try:
            q.submit("invalid_action_xyz", {"param": 1})
            assert False, "Should have raised ValueError"
        except ValueError as exc:
            assert "Unknown NX action" in str(exc)
            assert "invalid_action_xyz" in str(exc)
