"""A/B comparison runner — old single-shot vs new staged pipeline.

Runs both pipelines against the same hallucination-injected inputs and
measures which one catches more errors / produces higher quality output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tests.generative_cad.experiments.hallucination_metrics import (
    ExperimentComparison,
    GenerationMetrics,
    HallucinationCategory,
    HallucinationEvent,
)
from tests.generative_cad.experiments.mock_llm_injector import (
    HALLUCINATION_INJECTORS,
    generate_clean_raw,
    generate_injected_raw,
)


# ── Old pipeline (single-shot RawGcadDocument) ────────────────────────────────


def run_old_pipeline(raw_doc: dict) -> GenerationMetrics:
    """Simulate the old single-shot pipeline: LLM → RawGcadDocument → validate.

    The old pipeline trusts the LLM to output a complete RawGcadDocument.
    Hallucinations in the raw doc directly cause validation failures.
    """
    metrics = GenerationMetrics()

    # Stage 1: Parse
    from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document

    parse_result = parse_raw_gcad_document(raw_doc)
    if parse_result.ok:
        metrics.parse_success = True
    else:
        for issue in parse_result.issues:
            metrics.record(
                category=HallucinationCategory.SCHEMA,
                path=issue.path,
                detail=issue.message,
            )
        return metrics

    # Stage 2: Validate + Canonicalize
    from seekflow_engineering_tools.generative_cad.validation.pipeline import (
        validate_and_canonicalize,
    )
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

    canonical, report = validate_and_canonicalize(parse_result.document)
    if canonical and report.ok:
        metrics.validate_success = True
        metrics.canonicalize_success = True
    elif report:
        _classify_old_issues(report.issues, metrics)

    # Count ops and params
    if parse_result.document:
        doc = parse_result.document
        metrics.total_ops = len(doc.nodes)
        reg = default_registry()
        for node in doc.nodes:
            dialect = reg.get(node.dialect)
            if dialect:
                try:
                    spec = dialect.get_op_spec(node.op, node.op_version)
                    metrics.valid_ops += 1
                    try:
                        spec.validate_params(node.params)
                        metrics.valid_params += len(node.params)
                    except Exception:
                        pass
                except Exception:
                    metrics.invented_ops += 1
            metrics.total_params += len(node.params)

    return metrics


def _classify_old_issues(issues: list, metrics: GenerationMetrics) -> None:
    """Classify validation issues into hallucination categories for old pipeline."""
    for issue in issues:
        code = getattr(issue, "code", "")
        msg = getattr(issue, "message", "")
        path = getattr(issue, "path", "")
        combined = f"{code} {msg}".lower()

        if "unknown_dialect" in combined or "not registered" in combined:
            cat = HallucinationCategory.DIALECT
        elif "unknown_op" in combined or "not found" in combined:
            cat = HallucinationCategory.OP
        elif "op_version" in combined and ("unknown" in combined or "not found" in combined):
            cat = HallucinationCategory.OP_VERSION
        elif "extra" in combined and "param" in combined:
            cat = HallucinationCategory.PARAMS_EXTRA
        elif "missing" in combined and ("param" in combined or "required" in combined):
            cat = HallucinationCategory.PARAMS_MISSING
        elif "type" in combined and ("param" in combined or "invalid" in combined):
            cat = HallucinationCategory.PARAMS_TYPE
        elif "phase" in combined:
            cat = HallucinationCategory.PHASE
        elif "graph" in combined or "reference" in combined:
            cat = HallucinationCategory.GRAPH_WIRING
        elif "type" in combined and "mismatch" in combined:
            cat = HallucinationCategory.TYPE_MISMATCH
        elif "safety" in combined:
            cat = HallucinationCategory.SAFETY
        elif "constraint" in combined:
            cat = HallucinationCategory.CONSTRAINT
        elif "cross" in combined and "dialect" in combined:
            cat = HallucinationCategory.CROSS_DIALECT
        else:
            cat = HallucinationCategory.UNKNOWN

        metrics.record(cat, path=path, detail=msg)


# ── New pipeline (staged generation) ─────────────────────────────────────────


def run_new_pipeline(raw_doc: dict) -> GenerationMetrics:
    """Simulate the new staged pipeline.

    The new pipeline:
      1. Extracts a FeatureSequence from the raw doc (system-side, no LLM needed).
      2. Validates each node's params individually against OperationSpec.
      3. Assembles a fresh RawGcadDocument with system-filled fields.
      4. Validates the assembled document.

    This catches hallucinations at each stage before they propagate.
    """
    metrics = GenerationMetrics()

    # Stage 1: Extract feature sequence from raw doc
    from seekflow_engineering_tools.generative_cad.authoring.schemas import (
        ComponentDraft,
        FeatureSequenceDraft,
        NodePlanDraft,
    )
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

    reg = default_registry()

    # Build RoutePlan-like structure from the raw doc
    dialects_in_doc = {
        sd["dialect"] for sd in raw_doc.get("selected_dialects", [])
    }

    # Stage 2: Extract node plans (without params) and validate each
    node_plans = []
    param_drafts = {}
    for node in raw_doc.get("nodes", []):
        did = node.get("dialect", "")
        op = node.get("op", "")
        op_ver = node.get("op_version", "")
        phase = node.get("phase", "")

        # Check dialect exists
        dialect = reg.get(did)
        if dialect is None:
            metrics.record(HallucinationCategory.DIALECT, f"/nodes/{node.get('id')}/dialect",
                           f"Unknown dialect: {did!r}")
            continue

        # Check op exists
        try:
            spec = dialect.get_op_spec(op, op_ver)
        except Exception:
            metrics.record(HallucinationCategory.OP, f"/nodes/{node.get('id')}/op",
                           f"Unknown op: {did}.{op} v{op_ver}")
            metrics.invented_ops += 1
            continue

        # Check op_version matches
        if op_ver != spec.op_version:
            metrics.record(HallucinationCategory.OP_VERSION, f"/nodes/{node.get('id')}/op_version",
                           f"Wrong op_version: {op_ver!r} (expected {spec.op_version!r})")

        # Check phase
        if phase != spec.phase:
            metrics.record(HallucinationCategory.PHASE, f"/nodes/{node.get('id')}/phase",
                           f"Wrong phase: {phase!r} (expected {spec.phase!r})")

        # Check output names against OperationSpec output_types
        _OUTPUT_NAME_MAP: dict[str, str] = {
            "solid": "body", "frame": "outer_frame", "profile": "profile",
            "sketch": "sketch", "solid_array": "bodies", "plane": "plane",
            "point": "point", "curve": "curve", "face_set": "faces",
            "edge_set": "edges", "component_ref": "component",
        }
        expected_output_names = [_OUTPUT_NAME_MAP.get(t, t) for t in spec.output_types]

        actual_outputs = node.get("outputs", [])
        actual_names = [o.get("name", "") for o in actual_outputs]
        for i, ename in enumerate(expected_output_names):
            if i >= len(actual_names):
                metrics.record(HallucinationCategory.OUTPUT_NAMING,
                               f"/nodes/{node.get('id')}/outputs",
                               f"Missing output[{i}]: expected name={ename!r}")
            elif actual_names[i] != ename:
                metrics.record(HallucinationCategory.OUTPUT_NAMING,
                               f"/nodes/{node.get('id')}/outputs/{i}/name",
                               f"Wrong output name: {actual_names[i]!r} (expected {ename!r})")

        # Validate params individually
        from seekflow_engineering_tools.generative_cad.authoring.schemas import NodeParamsDraft
        try:
            spec.validate_params(node.get("params", {}))
            metrics.valid_params += len(node.get("params", {}))
        except Exception as e:
            _classify_param_error(str(e), node.get("id", ""), metrics)

        metrics.total_params += len(node.get("params", {}))
        metrics.valid_ops += 1
        metrics.total_ops += 1

        node_plans.append(NodePlanDraft(
            node_id=node["id"],
            component_id=node.get("component", "main"),
            dialect=did, op=op, op_version=spec.op_version,
            phase=spec.phase,
        ))
        param_drafts[node["id"]] = NodeParamsDraft(
            node_id=node["id"], dialect=did, op=op,
            op_version=spec.op_version, params=node.get("params", {}),
        )

    # Stage 3: Check safety
    safety = raw_doc.get("safety", {})
    required_safety = [
        "non_flight_reference_only", "not_airworthy", "not_certified",
        "not_for_manufacturing", "not_for_installation",
        "no_structural_validation", "no_life_prediction",
    ]
    for key in required_safety:
        if safety.get(key) is not True:
            metrics.record(HallucinationCategory.SAFETY, f"/safety/{key}",
                           f"Safety flag {key!r} is not True")

    # Stage 4: Check constraints
    constraints = raw_doc.get("constraints", {})
    for key in ("require_step_file", "require_metadata_sidecar", "require_closed_solid"):
        if constraints.get(key) is not True:
            metrics.record(HallucinationCategory.CONSTRAINT, f"/constraints/{key}",
                           f"Constraint {key!r} is not True")

    # Stage 5: Try assembly + validation
    try:
        from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
            assemble_raw_gcad_document,
        )
        from seekflow_engineering_tools.generative_cad.authoring.schemas import (
            FeatureSequenceDraft,
            RouteDecision,
            RoutePlan,
            SelectedDialectDraft,
        )

        route_plan = RoutePlan(
            route_decision=RouteDecision.GENERATIVE_CAD_IR,
            selected_dialects=[
                SelectedDialectDraft(dialect=d, version=(reg.get(d).version if reg.get(d) else "0.2.0"), reason="test")
                for d in dialects_in_doc if reg.get(d)
            ],
        )

        # Build components from raw doc
        components = []
        for comp in raw_doc.get("components", []):
            components.append(ComponentDraft(
                component_id=comp["id"],
                owner_dialect=comp.get("owner_dialect", list(dialects_in_doc)[0] if dialects_in_doc else ""),
            ))

        fs = FeatureSequenceDraft(
            components=components,
            node_sequence=node_plans,
        )

        assembly = assemble_raw_gcad_document(
            user_request="test",
            route_plan=route_plan,
            feature_sequence=fs,
            node_params=param_drafts,
            dialect_registry=reg,
        )

        # Validate assembled document
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize,
        )

        canonical, report = validate_and_canonicalize(assembly.raw_document)
        metrics.parse_success = True  # assembler always produces parseable output
        if canonical and report.ok:
            metrics.validate_success = True
            metrics.canonicalize_success = True
        elif report:
            _classify_old_issues(report.issues, metrics)

    except Exception as e:
        metrics.record(HallucinationCategory.UNKNOWN, "/assembly", str(e))

    return metrics


def _classify_param_error(error_msg: str, node_id: str, metrics: GenerationMetrics) -> None:
    """Classify a params_model validation error."""
    msg_lower = error_msg.lower()
    if "extra" in msg_lower or "unknown" in msg_lower or "unexpected" in msg_lower:
        metrics.extra_params += 1
        metrics.record(HallucinationCategory.PARAMS_EXTRA, f"/nodes/{node_id}/params", error_msg)
    elif "missing" in msg_lower or "required" in msg_lower:
        metrics.missing_params += 1
        metrics.record(HallucinationCategory.PARAMS_MISSING, f"/nodes/{node_id}/params", error_msg)
    elif "type" in msg_lower or "expected" in msg_lower or "invalid" in msg_lower:
        metrics.type_error_params += 1
        metrics.record(HallucinationCategory.PARAMS_TYPE, f"/nodes/{node_id}/params", error_msg)
    else:
        metrics.record(HallucinationCategory.PARAMS_RANGE, f"/nodes/{node_id}/params", error_msg)


# ── Experiment runner ────────────────────────────────────────────────────────


@dataclass
class ExperimentReport:
    """Full experiment report."""
    comparisons: list[ExperimentComparison] = field(default_factory=list)
    total_cases: int = 0
    old_avg_quality: float = 0.0
    new_avg_quality: float = 0.0
    avg_hallucination_reduction_pct: float = 0.0
    hallucination_detection_by_category: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_cases": self.total_cases,
            "old_avg_quality": round(self.old_avg_quality, 3),
            "new_avg_quality": round(self.new_avg_quality, 3),
            "quality_improvement": round(self.new_avg_quality - self.old_avg_quality, 3),
            "avg_hallucination_reduction_pct": round(self.avg_hallucination_reduction_pct, 1),
            "hallucination_detection_by_category": self.hallucination_detection_by_category,
            "comparisons": [c.to_dict() for c in self.comparisons],
        }


def run_full_experiment() -> ExperimentReport:
    """Run the full A/B experiment: all 10 hallucination types + clean baseline.

    For each hallucination type, runs both old and new pipelines and
    compares the results.
    """
    report = ExperimentReport()

    # Test each hallucination type
    for injection_id in sorted(HALLUCINATION_INJECTORS.keys()):
        raw_doc = generate_injected_raw(injection_id)
        comp = ExperimentComparison(
            case_id=injection_id,
            prompt=f"Injected: {HALLUCINATION_INJECTORS[injection_id][1]}",
            difficulty="injected",
        )
        comp.old_metrics = run_old_pipeline(raw_doc)
        comp.new_metrics = run_new_pipeline(raw_doc)
        report.comparisons.append(comp)

    # Also test clean (no hallucinations)
    clean_raw = generate_clean_raw()
    clean_comp = ExperimentComparison(
        case_id="clean_baseline",
        prompt="Clean washer (no injection)",
        difficulty="simple",
    )
    clean_comp.old_metrics = run_old_pipeline(clean_raw)
    clean_comp.new_metrics = run_new_pipeline(clean_raw)
    report.comparisons.append(clean_comp)

    # Compute aggregate statistics
    report.total_cases = len(report.comparisons)
    old_scores = [c.old_metrics.overall_quality_score for c in report.comparisons]
    new_scores = [c.new_metrics.overall_quality_score for c in report.comparisons]
    report.old_avg_quality = sum(old_scores) / len(old_scores) if old_scores else 0.0
    report.new_avg_quality = sum(new_scores) / len(new_scores) if new_scores else 0.0
    reductions = [c.hallucination_reduction for c in report.comparisons if c.case_id != "clean_baseline"]
    report.avg_hallucination_reduction_pct = (sum(reductions) / len(reductions) * 100) if reductions else 0.0

    # Per-category detection
    for comp in report.comparisons:
        for cat, count in comp.new_metrics.by_category.items():
            if cat not in report.hallucination_detection_by_category:
                report.hallucination_detection_by_category[cat] = {"old": 0, "new": 0}
        for cat, count in comp.old_metrics.by_category.items():
            if cat not in report.hallucination_detection_by_category:
                report.hallucination_detection_by_category[cat] = {"old": 0, "new": 0}
            report.hallucination_detection_by_category[cat]["old"] += count
        for cat, count in comp.new_metrics.by_category.items():
            if cat not in report.hallucination_detection_by_category:
                report.hallucination_detection_by_category[cat] = {"old": 0, "new": 0}
            report.hallucination_detection_by_category[cat]["new"] += count

    return report
