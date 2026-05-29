"""Skills orchestrator — Level-1 routing + Level-2 authoring prompt builders."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import DIALECT_REGISTRY, export_dialect_catalog
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.skills.prompts import (
    LEVEL1_ROUTING_SYSTEM_PROMPT,
    LEVEL2_AUTHORING_SYSTEM_PROMPT,
    REPAIR_PATCH_SYSTEM_PROMPT_V2,
)
from seekflow_engineering_tools.generative_cad.skills.schemas import DialectSelectionPlan


def list_domain_skills() -> list[str]:
    """Return available domain skill IDs."""
    return ["generic_mechanical", "turbomachinery_reference"]


def load_domain_skill(skill_id: str) -> str:
    """Load a domain skill markdown by ID."""
    from pathlib import Path
    domain_dir = Path(__file__).parent / "domain"
    path = domain_dir / f"{skill_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"Domain skill not found: {skill_id}")
    return path.read_text(encoding="utf-8")


def build_level1_routing_prompt(
    user_request: str,
    dialect_catalog: dict | None = None,
    domain_skill_ids: list[str] | None = None,
) -> dict:
    """Build a Level-1 routing prompt for dialect selection."""
    if dialect_catalog is None:
        dialect_catalog = export_dialect_catalog()

    domain_skills = {}
    for sid in (domain_skill_ids or list_domain_skills()):
        try:
            domain_skills[sid] = load_domain_skill(sid)[:2000]
        except FileNotFoundError:
            pass

    return {
        "system": LEVEL1_ROUTING_SYSTEM_PROMPT,
        "user": user_request,
        "output_schema": DialectSelectionPlan.model_json_schema(),
        "catalog": dialect_catalog,
        "domain_skills": domain_skills,
    }


def build_level2_authoring_prompt(
    user_request: str,
    selection_plan: DialectSelectionPlan | dict,
    contracts: dict[str, dict] | None = None,
    usage_skills: dict[str, str] | None = None,
) -> dict:
    """Build a Level-2 authoring prompt for RawGcadDocument generation."""
    if isinstance(selection_plan, dict):
        selection_plan = DialectSelectionPlan.model_validate(selection_plan)

    if contracts is None:
        contracts = {}
        for sd in selection_plan.selected_dialects:
            dialect = DIALECT_REGISTRY.get(sd.dialect)
            if dialect is not None:
                contracts[sd.dialect] = dialect.contract()

    return {
        "system": LEVEL2_AUTHORING_SYSTEM_PROMPT,
        "user": user_request,
        "output_schema": RawGcadDocument.model_json_schema(),
        "selected_dialects": [sd.model_dump() for sd in selection_plan.selected_dialects],
        "contracts": contracts,
        "usage_skills": usage_skills or {},
    }


def build_repair_prompt_v2(
    raw_document: dict,
    validation_report: dict,
    repair_state: dict,
) -> dict:
    """Build a repair prompt for iterative patch generation."""
    from seekflow_engineering_tools.generative_cad.repair.patch import RepairPatchV2

    return {
        "system": REPAIR_PATCH_SYSTEM_PROMPT_V2,
        "user": (
            f"RawGcadDocument: {raw_document}\n\n"
            f"Validation Issues: {validation_report.get('issues', [])}\n\n"
            f"Repair State: {repair_state}"
        ),
        "output_schema": RepairPatchV2.model_json_schema(),
    }
