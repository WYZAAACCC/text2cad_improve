"""Authoring context builder — loads only selected dialects.

Enforces:
  - Load only route_plan.selected_dialects.
  - Fail if selected dialect is not registered.
  - Fail if selected dialect has no BasePackage.
  - Fail if BasePackage.contract_hash != dialect contract hash.
  - Generate Level-2 usage skill from current contract.
  - Do not include unselected dialect operations.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from seekflow_engineering_tools.generative_cad.authoring.schemas import RoutePlan
from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash


class AuthoringContext(BaseModel):
    """Context for Level-2 authoring — selected dialects only."""

    model_config = ConfigDict(extra="forbid")

    route_plan: RoutePlan
    selected_dialects: list[str]
    dialect_contracts: dict[str, dict]
    level2_usage_skills: dict[str, str]
    tool_schema_hash: str = ""
    context_hash: str = ""

    def compute_hashes(self) -> "AuthoringContext":
        """Compute tool_schema_hash and context_hash."""
        self.context_hash = stable_hash({
            "selected_dialects": sorted(self.selected_dialects),
            "contracts": self.dialect_contracts,
            "usage_skill_hashes": {
                k: stable_hash(v) for k, v in self.level2_usage_skills.items()
            },
        })
        return self


def build_authoring_context(
    *,
    route_plan: RoutePlan,
    dialect_registry,  # DialectRegistry
    base_package_registry,  # BasePackageRegistry
) -> AuthoringContext:
    """Build authoring context for only the selected dialects.

    Raises:
        ValueError: If a selected dialect is not registered, has no
            BasePackage, or has a contract hash mismatch.
    """
    selected_dialects: list[str] = []
    dialect_contracts: dict[str, dict] = {}
    level2_usage_skills: dict[str, str] = {}

    for sd in route_plan.selected_dialects:
        did = sd.dialect

        # 1. Dialect must be registered
        dialect = dialect_registry.get(did)
        if dialect is None:
            raise ValueError(
                f"Selected dialect {did!r} is not registered. "
                f"Available: {dialect_registry.list_ids()}"
            )

        # 2. BasePackage must exist
        pkg = base_package_registry.get(did)
        if pkg is None:
            raise ValueError(
                f"Selected dialect {did!r} has no registered BasePackage. "
                f"Available: {base_package_registry.list_ids()}"
            )

        # 3. Contract hash must match
        from seekflow_engineering_tools.generative_cad.ir.hashing import contract_hash
        current_hash = contract_hash(dialect.contract())
        if pkg.contract_hash != current_hash:
            raise ValueError(
                f"BasePackage.contract_hash mismatch for {did!r}: "
                f"package={pkg.contract_hash[:16]}... "
                f"dialect={current_hash[:16]}..."
            )

        selected_dialects.append(did)
        dialect_contracts[did] = dialect.contract()

        # 4. Load Level-2 usage skill
        level2_usage_skills[did] = pkg.level2_usage_markdown

    # Compute context hash
    ctx = AuthoringContext(
        route_plan=route_plan,
        selected_dialects=selected_dialects,
        dialect_contracts=dialect_contracts,
        level2_usage_skills=level2_usage_skills,
    )
    ctx.compute_hashes()

    return ctx
