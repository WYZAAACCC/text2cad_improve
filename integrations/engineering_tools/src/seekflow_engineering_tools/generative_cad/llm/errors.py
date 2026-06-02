"""LLM provider errors."""
from __future__ import annotations


class LlmToolCallError(Exception):
    """Raised when tool calling fails at the provider level."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code or "llm_tool_call_error"


class LlmProviderError(Exception):
    """Raised for provider-level transport / auth / timeout errors."""

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.code = code or "llm_provider_error"
        self.status_code = status_code
