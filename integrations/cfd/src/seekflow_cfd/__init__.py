"""Independent CFD orchestration; importing this package never loads CAD/Ansys."""

from .agents import ExpertTeam
from .backends import Capabilities, MockBackend
from .models import CFDError, SimulationSpec
from .orchestrator import CFDOrchestrator

__all__ = [
    "CFDError",
    "CFDOrchestrator",
    "Capabilities",
    "ExpertTeam",
    "MockBackend",
    "SimulationSpec",
]
