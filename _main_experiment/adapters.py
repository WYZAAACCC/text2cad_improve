"""Thin adapters to existing experimental helpers.

All imports are lazy so importing this module does not mutate sys.path or pull
in CadQuery until a feature is actually used.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_PARAM_EXPERIMENT_DIR = ROOT / "_param_experiment"
_ENGINEERING_SRC = ROOT / "integrations" / "engineering_tools" / "src"


def _ensure_experiment_paths() -> None:
    for path in (_PARAM_EXPERIMENT_DIR, _ENGINEERING_SRC):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def load_mcp_tool_registry() -> dict[str, dict[str, Any]]:
    _ensure_experiment_paths()
    from mcp_tools import TOOLS

    return TOOLS


def call_mcp_tool(tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    tools = load_mcp_tool_registry()
    tool = tools.get(tool_name)
    if tool is None:
        raise KeyError(f"unknown MCP tool: {tool_name}")
    return tool["handler"](dict(args or {}))


def build_template_document(params: dict[str, Any]) -> dict[str, Any]:
    _ensure_experiment_paths()
    from param_templates import build

    return build(dict(params))


def load_design_families() -> dict[str, dict[str, Any]]:
    _ensure_experiment_paths()
    from design_families import DESIGN_FAMILIES

    return DESIGN_FAMILIES


def run_regeneration(
    task_id: str,
    params: dict[str, Any] | None = None,
    *,
    copy: bool = False,
) -> dict[str, Any]:
    _ensure_experiment_paths()
    from run_regen import run_one

    return run_one(task_id, params or {}, copy=copy)
