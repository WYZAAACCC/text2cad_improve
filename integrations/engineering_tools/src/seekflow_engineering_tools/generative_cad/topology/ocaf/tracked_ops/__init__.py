"""Tracked OCCT Builder operations — drop-in replacements for CadQuery shapes.* functions.

Each function executes the SAME OCCT Builder as the corresponding CadQuery function,
with ONE addition: history capture. This guarantees identical geometry (verified by
A/B volume/face/validity comparison).

PR-1 scope: standalone library. No connection to dialect handlers or OCAF Writer.
"""

from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_cut,
    tracked_fuse,
    tracked_common,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
    tracked_extrude,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.revolve import (
    tracked_revolve,
)

__all__ = [
    "tracked_cut",
    "tracked_fuse",
    "tracked_common",
    "tracked_extrude",
    "tracked_revolve",
]
