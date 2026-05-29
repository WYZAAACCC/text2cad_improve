"""Dialect registry — fail-closed registration with forbidden part-name checks."""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.dialects.base import BaseDialect
from seekflow_engineering_tools.generative_cad.ir.hashing import contract_hash

DIALECT_REGISTRY: dict[str, BaseDialect] = {}

FORBIDDEN_PART_TOKENS = {
    "turbine_disk",
    "flange",
    "bracket",
    "gearbox",
    "bearing",
}


def register_dialect(dialect: BaseDialect) -> None:
    did = dialect.dialect_id
    if did in DIALECT_REGISTRY:
        raise ValueError(f"duplicate dialect_id: {did}")
    if not did:
        raise ValueError("dialect_id must be non-empty")
    for token in FORBIDDEN_PART_TOKENS:
        if token in did:
            raise ValueError(
                f"dialect_id {did!r} appears to name a part, not a CAD grammar dialect"
            )
    DIALECT_REGISTRY[did] = dialect


def get_dialect(dialect_id: str) -> BaseDialect | None:
    return DIALECT_REGISTRY.get(dialect_id)


def require_dialect(dialect_id: str) -> BaseDialect:
    dialect = DIALECT_REGISTRY.get(dialect_id)
    if dialect is None:
        raise KeyError(f"unknown dialect: {dialect_id!r}")
    return dialect


def list_dialects() -> list[str]:
    return sorted(DIALECT_REGISTRY)


def export_dialect_catalog() -> dict[str, Any]:
    return {
        "catalog_version": "0.2.0",
        "dialects": [
            DIALECT_REGISTRY[k].manifest()
            for k in sorted(DIALECT_REGISTRY)
        ],
    }


def dialect_contract_hash(dialect_id: str) -> str:
    d = require_dialect(dialect_id)
    return contract_hash(d.contract())


def populate_registry() -> None:
    from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.dialect import (
        AXISYMMETRIC_DIALECT,
    )
    from seekflow_engineering_tools.generative_cad.dialects.sketch_extrude.dialect import (
        SKETCH_EXTRUDE_DIALECT,
    )
    from seekflow_engineering_tools.generative_cad.dialects.composition.dialect import (
        COMPOSITION_DIALECT,
    )

    register_dialect(AXISYMMETRIC_DIALECT)
    register_dialect(SKETCH_EXTRUDE_DIALECT)
    register_dialect(COMPOSITION_DIALECT)


populate_registry()
