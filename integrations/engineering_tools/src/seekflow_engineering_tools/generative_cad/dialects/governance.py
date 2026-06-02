"""Dialect governance — prevent dialects and ops from becoming concrete part primitives.

This module enforces the architectural boundary:
  - Primitive = deterministic part kernel (already exists, must not be touched).
  - BasePackage = LLM-facing authoring package (no execution).
  - Dialect = compiler/runtime ABI (operations must be grammar-generic, not part-specific).

Governance rules:
  1. Reject part-named dialects (e.g., "turbine_disk", "bracket_base").
  2. Reject make_xxx concrete part ops (e.g., "make_flange", "make_bracket").
  3. Allow typical_parts only in manifest routing text.
  4. Keep graph grammar generic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Forbidden tokens ──────────────────────────────────────────────────────────

FORBIDDEN_DIALECT_TOKENS: set[str] = {
    "bracket",
    "flange",
    "turbine_disk",
    "gearbox",
    "bearing_seat",
    "mounting_plate",
    "shaft_with_keyway",
    "impeller",
    "pump_housing",
    "pulley",
    "rotor",
    "stator",
    "motor_mount",
    "clamp_block",
    "heatsink",
    "engine_block",
    "cylinder_head",
    "crankshaft",
    "camshaft",
    "piston",
    "connecting_rod",
}

FORBIDDEN_OP_PREFIXES: set[str] = {
    "make_",
    "create_standard_",
    "generate_part_",
    "build_part_",
}

FORBIDDEN_OP_EXACT: set[str] = {
    "make_bracket",
    "make_flange",
    "make_turbine_disk",
    "make_gearbox",
    "make_bearing_seat",
    "make_mounting_plate",
    "make_impeller",
    "make_pump_housing",
    "make_pulley",
    "make_rotor",
    "make_washer",
    "make_ring",
    "make_hub",
    "make_spacer",
    "make_base_plate",
    "make_clamp",
    "make_heatsink",
}

# ── Governance result ─────────────────────────────────────────────────────────


@dataclass
class GovernanceIssue:
    code: str
    message: str
    severity: str = "error"


@dataclass
class GovernanceReport:
    ok: bool
    issues: list[GovernanceIssue] = field(default_factory=list)

    @classmethod
    def pass_(cls) -> "GovernanceReport":
        return cls(ok=True)

    @classmethod
    def fail(cls, code: str, message: str) -> "GovernanceReport":
        return cls(ok=False, issues=[GovernanceIssue(code=code, message=message)])


# ── Validation ────────────────────────────────────────────────────────────────


def validate_dialect_id(dialect_id: str) -> GovernanceReport:
    """Check that a dialect_id does not name a concrete part."""
    issues: list[GovernanceIssue] = []

    did_lower = dialect_id.lower().replace("-", "_")
    for token in FORBIDDEN_DIALECT_TOKENS:
        if token in did_lower:
            issues.append(GovernanceIssue(
                code="part_named_dialect",
                message=(
                    f"dialect_id {dialect_id!r} contains forbidden part token "
                    f"{token!r}. Dialects must be named after modeling paradigms "
                    f"(e.g., axisymmetric, sketch_extrude), not concrete parts."
                ),
            ))
            break

    return GovernanceReport(ok=len(issues) == 0, issues=issues)


def validate_op_name(op_name: str) -> GovernanceReport:
    """Check that an op name is not a concrete part op."""
    issues: list[GovernanceIssue] = []

    # Check exact forbidden names
    if op_name in FORBIDDEN_OP_EXACT:
        issues.append(GovernanceIssue(
            code="make_part_operation",
            message=(
                f"Operation {op_name!r} is a forbidden part-specific op. "
                f"Operations must be grammar-generic (e.g., revolve_profile, "
                f"extrude_rectangle), not part templates."
            ),
        ))

    # Check forbidden prefixes
    for prefix in FORBIDDEN_OP_PREFIXES:
        if op_name.startswith(prefix):
            issues.append(GovernanceIssue(
                code="make_part_operation",
                message=(
                    f"Operation {op_name!r} uses forbidden prefix {prefix!r}. "
                    f"Operations must be grammar-generic."
                ),
            ))
            break

    return GovernanceReport(ok=len(issues) == 0, issues=issues)


def validate_manifest_governance(manifest: dict[str, Any]) -> GovernanceReport:
    """Check that a manifest does not claim manufacturing readiness."""
    issues: list[GovernanceIssue] = []

    title = manifest.get("title", "")
    summary = manifest.get("summary", "")

    manufacturing_claims = [
        "manufacturing-ready",
        "production-ready",
        "certified",
        "airworthy",
        "flight-rated",
        "structural truth",
    ]

    combined = (title + " " + summary).lower()
    for claim in manufacturing_claims:
        if claim in combined:
            issues.append(GovernanceIssue(
                code="manufacturing_claim_in_manifest",
                message=(
                    f"Manifest title/summary contains '{claim}'. "
                    f"Generative CAD output is reference geometry only "
                    f"— do not claim manufacturing readiness."
                ),
                severity="warning",
            ))
            break

    return GovernanceReport(ok=len(issues) == 0, issues=issues)


def validate_dialect_governance(dialect: Any) -> GovernanceReport:
    """Full governance check for a dialect.

    Checks:
      1. dialect_id does not name a concrete part.
      2. No op is a make_xxx concrete part op.
      3. Manifest does not claim manufacturing readiness.
      4. OperationSpec summaries do not describe specific parts.
    """
    all_issues: list[GovernanceIssue] = []

    # 1. Dialect ID
    id_report = validate_dialect_id(dialect.dialect_id)
    all_issues.extend(id_report.issues)

    # 2. Operation names
    for (op_name, _op_ver), spec in dialect.op_specs().items():
        op_report = validate_op_name(op_name)
        all_issues.extend(op_report.issues)

        # 3. OperationSpec summary check
        summary = getattr(spec, "summary", None)
        if summary:
            summary_lower = summary.lower()
            for token in FORBIDDEN_DIALECT_TOKENS:
                if token in summary_lower:
                    all_issues.append(GovernanceIssue(
                        code="part_specific_op_summary",
                        message=(
                            f"OperationSpec {op_name!r} summary mentions "
                            f"'{token}'. Summaries should describe the geometric "
                            f"operation generically, not specific parts."
                        ),
                        severity="warning",
                    ))
                    break

    # 4. Manifest
    try:
        manifest = dialect.manifest()
        manifest_report = validate_manifest_governance(manifest)
        all_issues.extend(manifest_report.issues)
    except Exception:
        pass

    errors = [i for i in all_issues if i.severity == "error"]
    return GovernanceReport(ok=len(errors) == 0, issues=all_issues)


# ── Registry enforcement ──────────────────────────────────────────────────────


def enforce_governance_on_registry(registry: Any) -> GovernanceReport:
    """Run governance validation on all dialects in a registry.

    Call this after building a registry (before freeze) to catch governance
    violations early.

    Returns a consolidated GovernanceReport.
    """
    all_issues: list[GovernanceIssue] = []

    for did in registry.list_ids():
        dialect = registry.require(did)
        report = validate_dialect_governance(dialect)
        all_issues.extend(report.issues)

    errors = [i for i in all_issues if i.severity == "error"]
    return GovernanceReport(ok=len(errors) == 0, issues=all_issues)
