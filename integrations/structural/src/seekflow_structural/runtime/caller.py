"""Building the one thing that talks to the model.

Six standalone agent scripts each constructed their own OpenAI client and
their own request body. The client abstraction already existed in
`generative_cad/llm/` - the CFD expert team uses it - but the structural
agents imported only the schema helper and rolled their own loop. This puts
them back on the shared caller, so a change to how the model is addressed (a
timeout, a retry, the thinking flag) is made once.
"""
from __future__ import annotations

import os
from pathlib import Path

from seekflow_engineering_tools.generative_cad.llm.deepseek_client import (
    DeepSeekToolCaller,
)
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig

from seekflow_structural.errors import StructuralError

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com/beta"


def load_api_key(api_key_file: Path | None = None) -> str:
    """The key, from the file if given, otherwise from the environment.

    The file wins when present and is read into the environment so the shared
    caller - which looks the key up by name - finds it without being told.
    """
    if api_key_file is not None:
        path = Path(api_key_file)
        if not path.is_file():
            raise StructuralError(
                "api_key_file_missing", f"{path} is not a file", "preflight"
            )
        os.environ["DEEPSEEK_API_KEY"] = path.read_text(
            encoding="utf-8"
        ).strip()
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise StructuralError(
            "api_key_missing",
            "no API key: pass --api-key-file or set DEEPSEEK_API_KEY",
            "preflight",
        )
    return key


def model_config(
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout_s: int = 180,
) -> LlmModelConfig:
    """Deterministic by default, with thinking off.

    Every agent in this chain makes a measurement-backed decision rather than
    a creative one, and a run that is reproducible is a run whose trace can be
    re-read. Thinking is disabled for the same reason the upstream scripts
    disabled it: `tool_choice="required"` is only honoured without it.
    """
    return LlmModelConfig(
        model=model,
        base_url=base_url,
        timeout_s=timeout_s,
        temperature=0,
        thinking={"type": "disabled"},
    )


def build_caller(
    api_key_file: Path | None = None,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout_s: int = 180,
) -> tuple[DeepSeekToolCaller, LlmModelConfig]:
    load_api_key(api_key_file)
    return DeepSeekToolCaller(), model_config(model, base_url, timeout_s)
