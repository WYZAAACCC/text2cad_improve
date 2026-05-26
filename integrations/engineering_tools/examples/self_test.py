"""Offline self-test — validates tool registration and policy without hardware.

Usage:
    python examples/self_test.py
    python examples/self_test.py --ansys
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.registry import build_engineering_tools


def main():
    parser = argparse.ArgumentParser(description="Engineering tools self-test")
    parser.add_argument("--ansys", action="store_true", help="Test ANSYS 18.1")
    parser.add_argument("--solidworks", action="store_true", help="Test SolidWorks 2025")
    parser.add_argument("--nx", action="store_true", help="Test NX 18.0")
    parser.add_argument("--all", action="store_true", help="Test all")
    args = parser.parse_args()

    test_all = args.all or not (args.ansys or args.solidworks or args.nx)

    workspace = Path(__file__).resolve().parents[1] / "test_workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    config = EngineeringToolsConfig(
        workspace_root=workspace,
        solidworks_enabled=test_all or args.solidworks,
        nx_enabled=test_all or args.nx,
        ansys_enabled=test_all or args.ansys,
        ansys181_exe=Path("ansys181.exe"),  # will show as missing
    )

    print("=" * 60)
    print("SeekFlow Engineering Tools — Self Test")
    print(f"Workspace: {workspace}")
    print(f"SolidWorks: {'enabled' if config.solidworks_enabled else 'disabled'}")
    print(f"NX:         {'enabled' if config.nx_enabled else 'disabled'}")
    print(f"ANSYS:      {'enabled' if config.ansys_enabled else 'disabled'}")
    print()

    tools = build_engineering_tools(config)

    errors = 0
    for tool in tools:
        has_policy = tool.policy is not None
        has_name = bool(tool.name)
        has_desc = bool(tool.description)
        has_params = bool(tool.parameters)

        status = "PASS" if all([has_policy, has_name, has_desc, has_params]) else "FAIL"
        if status == "FAIL":
            errors += 1
            print(
                f"  [{status}] {tool.name}: "
                f"policy={has_policy}, name={has_name}, "
                f"desc={has_desc}, params={has_params}"
            )
        else:
            risk = tool.policy.risk
            caps = ",".join(sorted(tool.policy.capabilities)[:3])
            print(f"  [OK] {tool.name:45s} risk={risk:12s} caps={caps}")

    print()
    print(f"Total: {len(tools)} tools, {errors} errors")

    sys.exit(1 if errors > 0 else 0)


if __name__ == "__main__":
    main()
