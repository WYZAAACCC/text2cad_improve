"""G-CAD Core IR value types."""

from __future__ import annotations

from typing import Literal

ValueType = Literal[
    "solid",
    "solid_array",
    "frame",
    "plane",
    "point",
    "curve",
    "profile",
    "sketch",
    "face_set",
    "edge_set",
    "component_ref",
]
