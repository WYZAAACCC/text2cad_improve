"""SeekFlow Engineering Tools - SolidWorks 2025, NX 18.0, ANSYS 18.1 bridges.

Provides auditable, policy-enforced tools for local CAD/CAE automation.
"""

from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.registry import (
    ENGINEERING_CAPABILITIES,
    EngineeringDeepSeekAgent,
    build_engineering_tools,
    enable_engineering_tools,
)

__all__ = [
    "EngineeringToolsConfig",
    "ENGINEERING_CAPABILITIES",
    "EngineeringDeepSeekAgent",
    "build_engineering_tools",
    "enable_engineering_tools",
]
__version__ = "0.1.0"
