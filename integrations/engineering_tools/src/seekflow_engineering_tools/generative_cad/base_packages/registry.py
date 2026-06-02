"""BasePackageRegistry — explicit, freezable registry of LLM authoring packages."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from seekflow_engineering_tools.generative_cad.base_packages.models import BasePackage


@dataclass
class BasePackageRegistry:
    """Explicit registry of BasePackages.

    BasePackages are LLM-facing authoring packages — they do NOT execute
    geometry. Use ``default_base_package_registry()`` for the production
    singleton, or instantiate directly for tests.
    """

    _packages: dict[str, BasePackage] = field(default_factory=dict)
    _frozen: bool = False

    # ── Mutation ──

    def register(self, package: BasePackage) -> None:
        """Register a BasePackage. Raises if frozen, duplicate, or id mismatch."""
        if self._frozen:
            raise RuntimeError("BasePackageRegistry is frozen")
        pid = package.manifest.package_id
        if not pid:
            raise ValueError("package_id must be non-empty")
        if pid != package.manifest.dialect_id:
            raise ValueError(
                f"package_id {pid!r} must equal dialect_id "
                f"{package.manifest.dialect_id!r}"
            )
        if pid in self._packages:
            raise ValueError(f"duplicate package_id: {pid!r}")
        self._packages[pid] = package

    def freeze(self) -> None:
        """Freeze the registry. No further registrations allowed."""
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    # ── Query ──

    def get(self, package_id: str) -> BasePackage | None:
        """Return the BasePackage for *package_id*, or None."""
        return self._packages.get(package_id)

    def require(self, package_id: str) -> BasePackage:
        """Return the BasePackage for *package_id*, raising KeyError if missing."""
        try:
            return self._packages[package_id]
        except KeyError as exc:
            raise KeyError(f"unknown BasePackage: {package_id!r}") from exc

    def list_ids(self) -> list[str]:
        """Return sorted list of registered package IDs."""
        return sorted(self._packages)

    def export_manifest_catalog(self) -> dict:
        """Export a lightweight catalog of all manifests for Level-1 routing."""
        return {
            "catalog_version": "0.1.0",
            "base_packages": [
                self._packages[k].manifest.model_dump()
                for k in sorted(self._packages)
            ],
        }


@lru_cache(maxsize=1)
def default_base_package_registry() -> BasePackageRegistry:
    """Return the frozen production BasePackageRegistry.

    Imports happen lazily inside the cached builder to avoid circular
    imports at module level.
    """
    from seekflow_engineering_tools.generative_cad.base_packages.axisymmetric.package import (
        AXISYMMETRIC_BASE_PACKAGE,
    )
    from seekflow_engineering_tools.generative_cad.base_packages.sketch_extrude.package import (
        SKETCH_EXTRUDE_BASE_PACKAGE,
    )
    from seekflow_engineering_tools.generative_cad.base_packages.composition.package import (
        COMPOSITION_BASE_PACKAGE,
    )
    from seekflow_engineering_tools.generative_cad.base_packages.sketch_profile.package import (
        SKETCH_PROFILE_BASE_PACKAGE,
    )

    reg = BasePackageRegistry()
    reg.register(AXISYMMETRIC_BASE_PACKAGE)
    reg.register(SKETCH_EXTRUDE_BASE_PACKAGE)
    reg.register(COMPOSITION_BASE_PACKAGE)
    reg.register(SKETCH_PROFILE_BASE_PACKAGE)
    reg.freeze()
    return reg
