"""spatial_contract.json sidecar validation.

When spatial_contract.json exists alongside canonical IR, validates:
1. File is valid JSON conforming to SpatialConstraintGraph schema
2. Constraint entities exist in canonical components (cross-check)
"""

from __future__ import annotations
import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    SpatialConstraintGraph,
)
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import (
    ValidationReport,
)


def validate_spatial_contract_if_present(
    doc: CanonicalGcadDocument,
    spatial_contract_path: Path | None = None,
) -> ValidationReport:
    """Validate spatial_contract.json sidecar.

    If no spatial_contract exists, returns a passing report (spatial frontend
    was not enabled — this is valid for single-component cases).
    """
    stage = "spatial_contract"

    if spatial_contract_path is None:
        return ValidationReport.ok_report(stage, stages_run=[stage])

    try:
        data = json.loads(spatial_contract_path.read_text(encoding="utf-8"))
        graph = SpatialConstraintGraph.model_validate(data)
    except (json.JSONDecodeError, ValueError) as e:
        return ValidationReport.fail(
            stage=stage,
            code="spatial_contract_invalid",
            message=f"spatial_contract.json is invalid: {e}",
            stages_run=[stage],
        )

    # Cross-check: constraint entities must exist in canonical components
    component_ids = {c.id for c in doc.components}
    for c in graph.constraints:
        for eid in c.entities:
            if eid not in component_ids:
                return ValidationReport.fail(
                    stage=stage,
                    code="spatial_contract_entity_mismatch",
                    message=(
                        f"Constraint '{c.constraint_id}' references entity '{eid}' "
                        f"not found in canonical components"
                    ),
                    stages_run=[stage],
                )

    return ValidationReport.ok_report(stage, stages_run=[stage])
