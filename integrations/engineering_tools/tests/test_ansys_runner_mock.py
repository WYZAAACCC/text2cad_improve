"""ANSYS APDL runner tests (mock subprocess, no real ANSYS needed)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from seekflow_engineering_tools.ansys.apdl_runner import AnsysAPDLRunner
from seekflow_engineering_tools.ansys.apdl_templates import (
    static_cantilever_beam_rect_apdl,
    list_templates,
    render_template,
)
from seekflow_engineering_tools.ansys.parsers import (
    parse_result_summary,
    scan_out_for_errors,
)


# ── Template tests ────────────────────────────────────────────────────────


class TestApdlTemplates:
    def test_cantilever_beam_produces_apdl(self):
        apdl = static_cantilever_beam_rect_apdl(200, 20, 20, 1000)
        assert "/PREP7" in apdl
        assert "SOLID185" in apdl
        assert "MAX_DISPLACEMENT_MM" in apdl

    def test_list_templates(self):
        names = list_templates()
        assert "static_cantilever_beam_rect" in names

    def test_render_template(self):
        apdl = render_template(
            "static_cantilever_beam_rect",
            length_mm=100,
            width_mm=10,
            height_mm=10,
            force_n=500,
        )
        assert "BLOCK,0,100,0,10,0,10" in apdl

    def test_render_unknown_template_raises(self):
        with pytest.raises(ValueError, match="Unknown APDL template"):
            render_template("nonexistent")


# ── Parser tests ──────────────────────────────────────────────────────────


class TestParsers:
    def test_parse_displacement(self, tmp_path: Path):
        summary = tmp_path / "result_summary.txt"
        summary.write_text("MAX_DISPLACEMENT_MM=0.42000000E+00\n")
        metrics = parse_result_summary(summary)
        assert metrics["max_displacement_mm"] == pytest.approx(0.42)

    def test_parse_missing_file(self, tmp_path: Path):
        metrics = parse_result_summary(tmp_path / "nonexistent.txt")
        assert metrics == {}

    def test_scan_out_for_errors(self, tmp_path: Path):
        out = tmp_path / "output.out"
        out.write_text("line1\n*** ERROR *** something went wrong\nline3\n")
        errors = scan_out_for_errors(out)
        assert len(errors) == 1
        assert "something went wrong" in errors[0]


# ── Runner tests ──────────────────────────────────────────────────────────


class TestAnsysAPDLRunner:
    def test_health_check_exe_exists(self, tmp_path: Path):
        fake_exe = tmp_path / "ansys181.exe"
        fake_exe.write_text("")
        runner = AnsysAPDLRunner(fake_exe, tmp_path)
        info = runner.health_check()
        assert info["exists"] is True

    def test_health_check_exe_missing(self, tmp_path: Path):
        fake_exe = tmp_path / "nonexistent.exe"
        runner = AnsysAPDLRunner(fake_exe, tmp_path)
        info = runner.health_check()
        assert info["exists"] is False

    def test_run_apdl_file_success(self, tmp_path: Path):
        """Simulate a successful ANSYS run with a fake exe + output."""
        fake_exe = tmp_path / "ansys181.exe"
        fake_exe.write_text("")

        inp = tmp_path / "input.inp"
        inp.write_text("/PREP7\nFINISH\n")

        job_dir = tmp_path / "job"
        job_dir.mkdir()

        # Determine output filename from -o flag in the command
        def fake_run(cmd, cwd, timeout_s, env=None, **kwargs):
            o_idx = cmd.index("-o") if "-o" in cmd else -1
            out_name = cmd[o_idx + 1] if o_idx >= 0 else "beam_job.out"
            out_path = Path(cwd) / out_name
            out_path.write_text("Solution done.\n")
            (Path(cwd) / "result_summary.txt").write_text(
                "MAX_DISPLACEMENT_MM=0.35000000E+00\n"
            )
            return {
                "cmd": cmd,
                "cwd": str(cwd),
                "returncode": 0,
                "elapsed_s": 1.0,
                "stdout": "",
                "stderr": "",
            }

        runner = AnsysAPDLRunner(fake_exe, tmp_path)
        with mock.patch(
            "seekflow_engineering_tools.ansys.apdl_runner.run_subprocess",
            side_effect=fake_run,
        ):
            result = runner.run_apdl_file(inp, job_dir, "test_job", timeout_s=10)

        assert result["has_error"] is False
        assert result["returncode"] == 0

    def test_run_apdl_detects_error_in_output(self, tmp_path: Path):
        fake_exe = tmp_path / "ansys181.exe"
        fake_exe.write_text("")

        inp = tmp_path / "input.inp"
        inp.write_text("")

        job_dir = tmp_path / "job"
        job_dir.mkdir()

        def fake_run(cmd, cwd, timeout_s, env=None, **kwargs):
            o_idx = cmd.index("-o") if "-o" in cmd else -1
            out_name = cmd[o_idx + 1] if o_idx >= 0 else "beam_job.out"
            out_path = Path(cwd) / out_name
            out_path.write_text("*** ERROR *** element distortion\n")
            return {
                "cmd": cmd,
                "cwd": str(cwd),
                "returncode": 0,
                "elapsed_s": 1.0,
                "stdout": "",
                "stderr": "",
            }

        runner = AnsysAPDLRunner(fake_exe, tmp_path)
        with mock.patch(
            "seekflow_engineering_tools.ansys.apdl_runner.run_subprocess",
            side_effect=fake_run,
        ):
            result = runner.run_apdl_file(inp, job_dir, "test_job", timeout_s=10)

        assert result["has_error"] is True

    def test_run_apdl_exe_not_found(self, tmp_path: Path):
        fake_exe = tmp_path / "nonexistent.exe"
        runner = AnsysAPDLRunner(fake_exe, tmp_path)
        with pytest.raises(FileNotFoundError):
            runner.run_apdl_file(tmp_path / "inp", tmp_path / "job", "j")
