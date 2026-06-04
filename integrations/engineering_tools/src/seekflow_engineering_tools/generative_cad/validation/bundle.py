"""ValidationBundle — structured validation reports for metadata and import gate."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


class ValidationBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    raw_stage_reports: dict[str, ValidationReport] = Field(default_factory=dict)
    canonicalize_report: ValidationReport | None = None
    canonical_stage_reports: dict[str, ValidationReport] = Field(default_factory=dict)
    # v6.3: Repair hints generated from accumulated validation issues.
    # Empty string means no hints needed (all checks passed).
    repair_hints: str = ""

    def to_metadata_dict(self) -> dict:
        core_issues = []
        for report in self.raw_stage_reports.values():
            core_issues.extend([i.model_dump() for i in report.issues])
        if self.canonicalize_report is not None:
            core_issues.extend([i.model_dump() for i in self.canonicalize_report.issues])

        raw_ok = all(r.ok for r in self.raw_stage_reports.values()) if self.raw_stage_reports else False
        canon_ok = self.canonicalize_report.ok if self.canonicalize_report else False

        dialect = self.canonical_stage_reports.get("dialect_semantics")
        preflight = self.canonical_stage_reports.get("geometry_preflight")

        return {
            "core_validation": {
                "ok": raw_ok and canon_ok,
                "stages": {k: v.model_dump() for k, v in self.raw_stage_reports.items()},
                "canonicalize": self.canonicalize_report.model_dump() if self.canonicalize_report else None,
                "issues": core_issues,
            },
            "dialect_semantics": dialect.model_dump() if dialect else {
                "ok": False, "stage": "dialect_semantics",
                "issues": [{"code": "missing_dialect_semantics_report", "message": "dialect_semantics report missing", "severity": "error"}],
            },
            "geometry_preflight": preflight.model_dump() if preflight else {
                "ok": False, "stage": "geometry_preflight",
                "issues": [{"code": "missing_geometry_preflight_report", "message": "geometry_preflight report missing", "severity": "error"}],
            },
        }
