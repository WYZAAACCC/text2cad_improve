"""Shared fixtures for text_to_cad_real tests."""

import os
import tempfile
from pathlib import Path

import pytest


def _load_api_key() -> str:
    """Load DeepSeek API key from the environment only."""
    return os.environ.get("DEEPSEEK_API_KEY", "")


@pytest.fixture(scope="session")
def api_key() -> str:
    """DeepSeek API key for LLM calls."""
    key = _load_api_key()
    if not key:
        pytest.skip("No DeepSeek API key available")
    return key


@pytest.fixture(scope="session")
def deepseek_client(api_key: str):
    """Create an OpenAI-compatible client for DeepSeek."""
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


@pytest.fixture(scope="function")
def test_workspace(tmp_path: Path) -> Path:
    """Per-test workspace directory."""
    ws = tmp_path / "seekflow_test"
    ws.mkdir(parents=True, exist_ok=True)
    return ws
