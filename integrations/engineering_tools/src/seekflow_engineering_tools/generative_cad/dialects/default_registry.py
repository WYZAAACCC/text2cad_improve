"""Default frozen registry — cached, no import-time side effects."""

from __future__ import annotations

from functools import lru_cache

from seekflow_engineering_tools.generative_cad.dialects.registry_core import DialectRegistry


def build_default_registry() -> DialectRegistry:
    from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.dialect import AXISYMMETRIC_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.sketch_extrude.dialect import SKETCH_EXTRUDE_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.composition.dialect import COMPOSITION_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.sketch_profile.dialect import SKETCH_PROFILE_DIALECT

    registry = DialectRegistry()
    registry.register(AXISYMMETRIC_DIALECT)
    registry.register(SKETCH_EXTRUDE_DIALECT)
    registry.register(COMPOSITION_DIALECT)
    registry.register(SKETCH_PROFILE_DIALECT)

    # ── Governance check before freeze ──
    from seekflow_engineering_tools.generative_cad.dialects.governance import (
        enforce_governance_on_registry,
    )
    gov_report = enforce_governance_on_registry(registry)
    if not gov_report.ok:
        error_msgs = "; ".join(i.message for i in gov_report.issues if i.severity == "error")
        raise RuntimeError(f"Dialect governance check failed: {error_msgs}")

    registry.freeze()
    return registry


@lru_cache(maxsize=1)
def default_registry() -> DialectRegistry:
    return build_default_registry()
