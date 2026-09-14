"""The face-evolution index: which face of the finished part a role names.

Reading a role means reading a corruptible `TNaming` attribute in a subprocess
and hoping it survives. The index does that once, up front, and turns the
question into a lookup - so the face-finding tools can ask "which faces came
from the groove cutter" without any of them touching the CAD kernel.

`build` is exported as `build_index`. The submodule is also called `build`,
and rebinding that name to the function makes `evolution.build.anything`
resolve against the function instead of the module - which is a confusing
failure to hand to the next person.
"""
from seekflow_structural.evolution.build import BuildReport
from seekflow_structural.evolution.build import build as build_index

__all__ = ["BuildReport", "build_index"]
