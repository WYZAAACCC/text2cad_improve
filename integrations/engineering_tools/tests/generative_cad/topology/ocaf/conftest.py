"""Shared fixtures for all OCAF topology tests (smoke + writer + ...)."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def ascii_tmpdir():
    """Create a temporary directory with pure ASCII path."""
    base = Path(tempfile.gettempdir()) / "ocaf_smoke_tests"
    base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=str(base), prefix="ascii_"))
    yield tmp
    import shutil
    try:
        shutil.rmtree(str(tmp), ignore_errors=True)
    except Exception:
        pass


@pytest.fixture
def chinese_tmpdir():
    """Create a temporary directory with Chinese characters in path."""
    base = Path(tempfile.gettempdir()) / "ocaf_smoke_tests"
    base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=str(base), prefix="中文测试_"))
    yield tmp
    import shutil
    try:
        shutil.rmtree(str(tmp), ignore_errors=True)
    except Exception:
        pass


@pytest.fixture
def xbf_path_ascii(ascii_tmpdir):
    """An ASCII .xbf file path that doesn't exist yet."""
    return ascii_tmpdir / "test_doc.xbf"


@pytest.fixture
def xbf_path_chinese(chinese_tmpdir):
    """A Chinese-path .xbf file path that doesn't exist yet."""
    return chinese_tmpdir / "测试文档.xbf"
