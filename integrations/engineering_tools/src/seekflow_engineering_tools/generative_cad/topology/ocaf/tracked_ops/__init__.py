"""Tracked OCCT Builder operations — drop-in replacements for CadQuery shapes.* functions.

Each function executes the SAME OCCT Builder as the corresponding CadQuery function,
with ONE addition: history capture. This guarantees identical geometry (verified by
A/B volume/face/validity comparison).
"""

from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_cut, tracked_fuse, tracked_common,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
    tracked_extrude,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.revolve import (
    tracked_revolve,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.fillet import (
    tracked_fillet,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.chamfer import (
    tracked_chamfer,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.unify import (
    tracked_unify,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.mirror import (
    tracked_mirror,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.pattern import (
    tracked_linear_pattern,
    tracked_circular_pattern,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.offset_sweep import (
    tracked_shell,
    tracked_sweep,
    tracked_loft,
)

__all__ = [
    "tracked_cut", "tracked_fuse", "tracked_common",
    "tracked_extrude", "tracked_revolve",
    "tracked_fillet", "tracked_chamfer", "tracked_unify",
    "tracked_mirror", "tracked_linear_pattern",
    "tracked_circular_pattern", "tracked_shell", "tracked_sweep", "tracked_loft",
]
