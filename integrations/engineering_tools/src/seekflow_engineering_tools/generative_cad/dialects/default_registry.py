"""Default frozen registry — cached, no import-time side effects."""

from __future__ import annotations

from functools import lru_cache

from seekflow_engineering_tools.generative_cad.dialects.registry_core import DialectRegistry


def build_default_registry() -> DialectRegistry:
    from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.dialect import AXISYMMETRIC_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.sketch_extrude.dialect import SKETCH_EXTRUDE_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.composition.dialect import COMPOSITION_DIALECT

    registry = DialectRegistry()
    registry.register(AXISYMMETRIC_DIALECT)
    registry.register(SKETCH_EXTRUDE_DIALECT)
    registry.register(COMPOSITION_DIALECT)
    registry.freeze()
    return registry


@lru_cache(maxsize=1)
def default_registry() -> DialectRegistry:
    return build_default_registry()
