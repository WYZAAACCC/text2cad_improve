"""Generative CAD base registry — explicit, deterministic, fail-closed."""

from __future__ import annotations

BASE_REGISTRY: dict = {}


def register_base(base) -> None:
    """Register a generative CAD base. Fails on duplicates or bad naming."""
    if base.base_id in BASE_REGISTRY:
        raise ValueError(f"Duplicate generative CAD base_id: {base.base_id}")
    if not base.base_id.endswith("_base"):
        raise ValueError("base_id must end with '_base'")
    forbidden_part_names = ["turbine_disk", "flange", "bracket", "gearbox", "bearing"]
    for token in forbidden_part_names:
        if token in base.base_id:
            raise ValueError(
                f"base_id {base.base_id!r} appears to name a part, not a CAD grammar"
            )
    BASE_REGISTRY[base.base_id] = base


def get_base(base_id: str):
    """Get a registered base by id, or None."""
    return BASE_REGISTRY.get(base_id)


def list_bases() -> list[str]:
    """Return sorted list of registered base ids."""
    return sorted(BASE_REGISTRY.keys())


def export_base_catalog() -> dict:
    """Export full catalog of registered bases for LLM consumption."""
    return {
        "base_catalog_version": "0.1.0",
        "bases": [
            BASE_REGISTRY[k].export_manifest() for k in sorted(BASE_REGISTRY.keys())
        ],
    }


def _populate_registry() -> None:
    """Explicit registration of MVP bases. No importlib magic."""
    from seekflow_engineering_tools.generative_cad.bases.axisymmetric.runner import (
        AXISYMMETRIC_BASE,
    )
    from seekflow_engineering_tools.generative_cad.bases.sketch_extrude.runner import (
        SKETCH_EXTRUDE_BASE,
    )

    register_base(AXISYMMETRIC_BASE)
    register_base(SKETCH_EXTRUDE_BASE)


_populate_registry()
