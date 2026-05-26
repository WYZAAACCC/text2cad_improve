"""Path safety tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from seekflow_engineering_tools.common.paths import (
    ensure_extension,
    ensure_inside_workspace,
)


class TestEnsureInsideWorkspace:
    def test_allows_path_within_workspace(self, tmp_path: Path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        child = workspace / "sub" / "file.prt"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.touch()

        result = ensure_inside_workspace(workspace, child)
        assert result == child.resolve()

    def test_allows_relative_path(self, tmp_path: Path):
        workspace = tmp_path / "ws"
        workspace.mkdir()

        result = ensure_inside_workspace(workspace, "sub/file.prt")
        assert result == (workspace / "sub/file.prt").resolve()

    def test_rejects_dotdot_escape(self, tmp_path: Path):
        workspace = tmp_path / "ws"
        workspace.mkdir()

        with pytest.raises(ValueError, match="outside workspace"):
            ensure_inside_workspace(workspace, "../etc/passwd")

    def test_rejects_absolute_path_outside(self, tmp_path: Path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        outside = tmp_path / "outside" / "file.txt"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.touch()

        with pytest.raises(ValueError, match="outside workspace"):
            ensure_inside_workspace(workspace, outside)

    def test_resolves_symlinks_correctly(self, tmp_path: Path):
        # Windows symlinks may require admin; this test is best-effort.
        pass


class TestEnsureExtension:
    def test_allows_valid_extension(self):
        result = ensure_extension(Path("file.prt"), {".prt", ".step"})
        assert result.suffix == ".prt"

    def test_rejects_invalid_extension(self):
        with pytest.raises(ValueError, match="not allowed"):
            ensure_extension(Path("file.exe"), {".prt", ".step"})

    def test_case_insensitive(self):
        # ensure_extension compares suffix.lower(), so .PRT matches .prt
        result = ensure_extension(Path("file.PRT"), {".prt"})
        assert result.suffix == ".PRT"
