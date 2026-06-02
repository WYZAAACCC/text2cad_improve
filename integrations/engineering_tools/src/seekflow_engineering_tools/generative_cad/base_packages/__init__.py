"""BasePackage — LLM-facing authoring packages.

BasePackage is NOT an executor. It does not import CadQuery, does not run
geometry, and does not contain runner source. Its job is to provide the LLM
with a curated authoring context: manifest, generated level-2 usage skill,
examples, anti-examples, and a contract hash for provenance.

Runtime execution lives in ``generative_cad.dialects``.
"""

from seekflow_engineering_tools.generative_cad.base_packages.models import (
    BasePackage,
    BasePackageAntiExample,
    BasePackageExample,
    BasePackageId,
    BasePackageManifest,
)
from seekflow_engineering_tools.generative_cad.base_packages.registry import (
    BasePackageRegistry,
    default_base_package_registry,
)

__all__ = [
    "BasePackage",
    "BasePackageAntiExample",
    "BasePackageExample",
    "BasePackageId",
    "BasePackageManifest",
    "BasePackageRegistry",
    "default_base_package_registry",
]
