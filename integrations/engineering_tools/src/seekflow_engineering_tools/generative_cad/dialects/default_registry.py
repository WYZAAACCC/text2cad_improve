"""Default frozen registry — cached, no import-time side effects."""

from __future__ import annotations

from functools import lru_cache

from seekflow_engineering_tools.generative_cad.dialects.registry_core import DialectRegistry


def build_default_registry() -> DialectRegistry:
    from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.dialect import AXISYMMETRIC_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.sketch_extrude.dialect import SKETCH_EXTRUDE_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.composition.dialect import COMPOSITION_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.sketch_profile.dialect import SKETCH_PROFILE_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.loft_sweep.dialect import LOFT_SWEEP_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.shell_housing.dialect import SHELL_HOUSING_DIALECT

    registry = DialectRegistry()
    registry.register(AXISYMMETRIC_DIALECT)
    registry.register(SKETCH_EXTRUDE_DIALECT)
    registry.register(COMPOSITION_DIALECT)
    registry.register(SKETCH_PROFILE_DIALECT)
    registry.register(LOFT_SWEEP_DIALECT)
    registry.register(SHELL_HOUSING_DIALECT)

    # ── Governance check before freeze ──
    from seekflow_engineering_tools.generative_cad.dialects.governance import (
        enforce_governance_on_registry,
    )
    gov_report = enforce_governance_on_registry(registry)
    if not gov_report.ok:
        error_msgs = "; ".join(i.message for i in gov_report.issues if i.severity == "error")
        raise RuntimeError(f"Dialect governance check failed: {error_msgs}")

    # ── Phase 4: Wire topology contracts to core operations ──
    from seekflow_engineering_tools.generative_cad.topology.contracts import (
        CONTRACT_REGISTRY,
    )

    _topology_required_ops = {
        ("axisymmetric", "revolve_profile"),
        ("sketch_extrude", "extrude_rectangle"),
        ("composition", "boolean_union"),
        ("composition", "boolean_cut"),
        ("sketch_profile", "revolve_profile"),
    }

    for dialect_name, op_name in _topology_required_ops:
        dialect = registry.require(dialect_name)
        try:
            op_spec = dialect.get_op_spec(op_name)
            contract_key = (dialect_name, op_name)
            if contract_key in CONTRACT_REGISTRY:
                op_spec.topology_contract = CONTRACT_REGISTRY[contract_key]
            op_spec.topology_mode = "required"
        except (KeyError, AttributeError):
            pass  # dialect or op not found — skip (test/compat)

    registry.freeze()
    return registry


@lru_cache(maxsize=1)
def default_registry() -> DialectRegistry:
    return build_default_registry()
