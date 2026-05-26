"""Example: SeekFlow Agent with engineering tools (health-check only).

This is a safe baseline that checks tool availability without running
actual CAD/CAE operations.

Usage:
    python examples/engineering_agent.py
"""

from __future__ import annotations

from pathlib import Path

from seekflow import DeepSeekAgent

from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.registry import enable_engineering_tools


def main():
    workspace = Path(os.environ.get("ENGINEERING_WORKSPACE", "D:/seekflow_workspace"))
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    config = EngineeringToolsConfig(
        workspace_root=workspace,
        solidworks_enabled=True,
        solidworks_visible=True,
        solidworks_part_template=Path(
            os.environ.get(
                "SOLIDWORKS_PART_TEMPLATE",
                r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\Part.prtdot",
            )
        ),
        nx_enabled=True,
        nx_job_root=workspace / "nx_jobs",
        ansys_enabled=True,
        ansys181_exe=Path(
            os.environ.get(
                "ANSYS181_EXE",
                r"C:\Program Files\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe",
            )
        ),
        ansys_default_timeout_s=600,
    )

    agent = DeepSeekAgent(
        role="Engineering Automation Agent",
        goal=(
            "Create CAD models and run CAE analyses through local approved "
            "tools only. Never invent file results. Always report tool output."
        ),
        backstory=(
            "You are connected to local SolidWorks 2025, NX 18.0, and "
            "ANSYS 18.1 through audited SeekFlow tools."
        ),
        dangerous_tools=True,
        max_steps=8,
    )

    enable_engineering_tools(agent, config)

    result = agent.run(
        "请检查 SolidWorks、NX、ANSYS 是否可用。列出每个软件的状态。"
    )
    print("=" * 60)
    print("Agent result:")
    print(result.final_output)
    print(f"Tokens: {result.tokens}, Cost: {result.cost:.4f} CNY")


import os

if __name__ == "__main__":
    main()
