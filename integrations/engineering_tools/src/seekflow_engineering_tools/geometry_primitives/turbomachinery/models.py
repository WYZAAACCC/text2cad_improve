"""Turbomachinery primitive definitions.

Reserved primitive names (NOT yet implemented):
  - axisymmetric_turbine_disk
  - parametric_turbine_blade

These will be registered when full implementations are ready:
  geometry kernel, compiler handler, metadata, mechanical validator, and tests.
"""

from seekflow_engineering_tools.geometry_primitives.base import PrimitiveDefinition

TURBOMACHINERY_PRIMITIVES: list[PrimitiveDefinition] = []
