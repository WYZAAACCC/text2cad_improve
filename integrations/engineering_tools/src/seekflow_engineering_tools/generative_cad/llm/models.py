"""LLM provider models and configuration."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class LlmProvider(str, Enum):
    DEEPSEEK = "deepseek"


class LlmModelRole(str, Enum):
    ROUTER = "router"
    AUTHOR = "author"
    REPAIR = "repair"


class LlmModelConfig(BaseModel):
    """Configuration for a single LLM model endpoint."""

    model_config = {"extra": "forbid"}

    provider: LlmProvider = LlmProvider.DEEPSEEK
    model: str
    base_url: str = "https://api.deepseek.com/beta"
    use_strict_tools: bool = True
    use_json_output_fallback: bool = False
    timeout_s: int = 90
    max_retries: int = 2
    temperature: float | None = None
    reasoning_enabled: bool = False
    reasoning_effort: str | None = None


class AuthoringLlmConfig(BaseModel):
    """Three-role LLM configuration for the full authoring pipeline."""

    model_config = {"extra": "forbid"}

    router: LlmModelConfig
    author: LlmModelConfig
    repair: LlmModelConfig


# ── Default DeepSeek config ──────────────────────────────────────────────────

DEFAULT_DEEPSEEK_CONFIG = AuthoringLlmConfig(
    router=LlmModelConfig(
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/beta",
        use_strict_tools=True,
    ),
    author=LlmModelConfig(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/beta",
        use_strict_tools=True,
    ),
    repair=LlmModelConfig(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/beta",
        use_strict_tools=True,
    ),
)
