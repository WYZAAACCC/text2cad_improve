""""""

from __future__ import annotations

from pathlib import Path

from seekflow_engineering_tools.ansys.tools import build_ansys_tools
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.nx.tools import build_nx_tools
from seekflow_engineering_tools.solidworks.tools import build_solidworks_tools

# ── Capability constants ────────────────────────────────────────────────

ENGINEERING_CAPABILITIES: set[str] = {
    "filesystem.read",
    "filesystem.write",
    "cad.solidworks.read",
    "cad.solidworks.write",
    "cad.nx.read",
    "cad.nx.write",
    "cae.ansys.read",
    "cae.ansys.write",
    "cae.ansys.solve",
}


# ── Tool builders ───────────────────────────────────────────────────────


def build_engineering_tools(config: EngineeringToolsConfig) -> list:
    """Return the full list of enabled engineering tools for *config*."""
    tools: list = []

    if config.solidworks_enabled:
        tools.extend(build_solidworks_tools(config))

    if config.nx_enabled:
        tools.extend(build_nx_tools(config))

    if config.ansys_enabled:
        tools.extend(build_ansys_tools(config))

    return tools


# ── Agent integration ───────────────────────────────────────────────────


def enable_engineering_tools(agent, config: EngineeringToolsConfig):
    """Attach engineering tools to an existing SeekFlow DeepSeekAgent.

    This helper updates the agent's capability profile (allowed capabilities,
    max risk, workspace root) and registers all enabled engineering tools.

    Usage::

        from seekflow import DeepSeekAgent
        agent = DeepSeekAgent(role="...", goal="...", backstory="...")
        enable_engineering_tools(agent, config)
        result = agent.run("用ANSYS算一个悬臂梁")
    """
    agent._allowed_capabilities.update(ENGINEERING_CAPABILITIES)
    agent._max_risk = "write"  # CAD/CAE tools need write access
    agent._workspace_root = str(config.workspace_root)

    agent.add_tools(build_engineering_tools(config))

    if hasattr(agent, "_invalidate_runtime"):
        agent._invalidate_runtime()

    return agent


class EngineeringDeepSeekAgent:
    """Factory that wraps a SeekFlow DeepSeekAgent with engineering tools.

    Usage::

        agent = EngineeringDeepSeekAgent.create(api_key="...", config=cfg)
        result = agent.run("create a box in SolidWorks")
    """

    @staticmethod
    def create(
        *,
        config: EngineeringToolsConfig,
        api_key: str | None = None,
        model: str = "deepseek-v4-pro",
        role: str = "Engineering Automation Agent",
        goal: str = (
            "Create CAD models and run CAE analyses through local approved "
            "tools only. Never invent file results. Always report tool output."
        ),
        backstory: str = (
            "You are connected to local SolidWorks 2025, NX 12.0, and "
            "ANSYS 18.1 through audited SeekFlow tools."
        ),
        **kwargs,
    ):
        from seekflow import DeepSeekAgent

        agent = DeepSeekAgent(
            role=role,
            goal=goal,
            backstory=backstory,
            api_key=api_key,
            model=model,
            dangerous_tools=True,
            **kwargs,
        )
        enable_engineering_tools(agent, config)
        return agent
