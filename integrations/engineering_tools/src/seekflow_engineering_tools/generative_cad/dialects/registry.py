"""Dialect registry — v0.3: delegates to frozen default_registry.

Compatibility wrappers preserve existing API (register_dialect, get_dialect,
require_dialect, list_dialects, export_dialect_catalog, dialect_contract_hash).

Import-time populate_registry() side effect removed. Use default_registry()
for the production registry or DialectRegistry() for isolated test instances.
"""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.dialects.base import BaseDialect
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.ir.hashing import contract_hash

# v6.3: DIALECT_REGISTRY global removed. Use default_registry() instead.
# All production code should call:
#   default_registry().require(dialect_id)
#   default_registry().get(dialect_id)
# The old global was a lazy-populated synonym that added unnecessary
# global mutable state. It has been replaced across all production code.
__DIALECT_REGISTRY_REMOVED_IN_V63__ = True

FORBIDDEN_PART_TOKENS = {
    "turbine_disk",
    "flange",
    "bracket",
    "gearbox",
    "bearing",
}


def _ensure_populated() -> None:
    """v6.3: No-op — default_registry() auto-initializes via lru_cache. Kept for compat."""
    pass


def register_dialect(dialect: BaseDialect) -> None:
    raise RuntimeError(
        "register_dialect is disabled. The default registry is frozen at import time. "
        "Use DialectRegistry() for isolated test instances. "
        "The DIALECT_REGISTRY global has been removed in v6.3 — use default_registry() instead."
    )


def get_dialect(dialect_id: str) -> BaseDialect | None:
    return default_registry().get(dialect_id)


def require_dialect(dialect_id: str) -> BaseDialect:
    return default_registry().require(dialect_id)


def list_dialects() -> list[str]:
    return default_registry().list_ids()


def export_dialect_catalog() -> dict[str, Any]:
    return default_registry().export_catalog()


def dialect_contract_hash(dialect_id: str) -> str:
    return default_registry().contract_hash(dialect_id)


def populate_registry() -> None:
    """No-op — default registry auto-initializes via lru_cache. Kept for compat."""
    _ensure_populated()
