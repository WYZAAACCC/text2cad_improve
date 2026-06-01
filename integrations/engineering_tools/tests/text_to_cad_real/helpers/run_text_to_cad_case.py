"""Unified text-to-CAD test runner.

Takes a natural language prompt through the full pipeline:
  NL prompt → Level-1 routing (LLM) → Level-2 authoring (LLM) or Primitive route
  → Build → STEP + metadata + artifact → import gate.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


# ── DeepSeek model ──
DEEPSEEK_MODEL = "deepseek-v4-pro"


@dataclass(frozen=True)
class TextToCadCase:
    """Test case specification."""
    case_id: str
    name: str
    prompt: str

    expected_outcome: Literal[
        "should_build",
        "should_route_to_primitive",
        "should_fail_closed",
        "capability_dependent",
    ] = "should_build"

    expected_route: Literal[
        "deterministic_primitive",
        "generative_cad_ir",
        "unsupported",
        "any",
    ] = "any"

    expected_primitive: str | None = None
    expected_dialects: list[str] = field(default_factory=list)

    required_artifacts: list[str] = field(default_factory=lambda: [
        "step", "metadata", "artifact", "logs",
    ])

    geometry_expectations: dict = field(default_factory=dict)
    metadata_expectations: dict = field(default_factory=dict)

    allow_repair: bool = True
    max_repair_attempts: int = 2

    strict_import_gate: bool = True


@dataclass
class TextToCadResult:
    """Result of running a text-to-CAD case."""
    case_id: str
    ok: bool
    expected_outcome: str
    actual_route: str = ""
    step_path: Path | None = None
    metadata_path: Path | None = None
    artifact_path: Path | None = None
    import_gate_path: Path | None = None
    logs_path: Path | None = None
    case_dir: Path | None = None
    error: str | None = None
    error_stage: str = ""
    error_code: str = ""
    route_plan: dict | None = None
    raw_gcad: dict | None = None
    validation_seed: dict | None = None
    import_gate_result: dict | None = None
    repair_attempts: int = 0
    warnings: list[str] = field(default_factory=list)
    logs: list[dict] = field(default_factory=list)
    validation_stages: dict = field(default_factory=dict)

    @property
    def step_exists(self) -> bool:
        return self.step_path is not None and self.step_path.exists()

    @property
    def metadata_exists(self) -> bool:
        return self.metadata_path is not None and self.metadata_path.exists()


# ── Stage names for structured logging ──
STAGE_ORDER = [
    "prompt_received",
    "routing_start",
    "routing_result",
    "dialect_contract_loaded",
    "authoring_start",
    "raw_gcad_generated",
    "parse_result",
    "validation_result",
    "canonicalization_result",
    "build_start",
    "runner_start",
    "operation_execution",
    "runtime_postconditions",
    "step_export",
    "step_inspection",
    "metadata_written",
    "artifact_written",
    "import_gate_result",
    "repair_attempt",
    "repair_stopped",
    "case_summary",
]


def _log_event(logs: list[dict], case_id: str, stage: str, event: str,
               ok: bool = True, details: dict | None = None) -> None:
    logs.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "case_id": case_id,
        "stage": stage,
        "event": event,
        "ok": ok,
        "details": details or {},
    })


def _call_deepseek_tool(
    client,
    system_prompt: str,
    user_prompt: str,
    tools: list[dict],
    tool_choice: dict,
    model: str = DEEPSEEK_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> dict:
    """Call DeepSeek API with function calling (tools) and return parsed JSON args.

    Uses OpenAI-compatible function calling to enforce schema compliance
    via enum constraints on dialect names, operation names, and phases.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    msg = response.choices[0].message
    if msg.tool_calls and len(msg.tool_calls) > 0:
        return json.loads(msg.tool_calls[0].function.arguments)
    # Fallback: try to parse content as JSON (shouldn't happen with tool_choice)
    if msg.content:
        return _parse_llm_json(msg.content)
    raise RuntimeError("DeepSeek returned neither tool_calls nor content")


def _parse_llm_json(response_text: str) -> dict:
    """Parse JSON from LLM response, handling markdown fences."""
    text = response_text.strip()
    if text.startswith("```"):
        # Remove markdown fences
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


def run_text_to_cad_case(
    case: TextToCadCase,
    workspace: Path,
    client,
    *,
    api_key: str = "",
    skip_llm: bool = False,
) -> TextToCadResult:
    """Run a single text-to-CAD test case through the full pipeline.

    Args:
        case: Test case specification.
        workspace: Root workspace directory for this test.
        client: OpenAI-compatible client for LLM calls.
        api_key: API key (for env isolation).
        skip_llm: If True, skip actual LLM calls (for unit-testing the framework).

    Returns:
        TextToCadResult with all output paths and status.
    """
    logs: list[dict] = []
    case_dir = workspace / case.case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    # Write prompt.txt
    (case_dir / "prompt.txt").write_text(case.prompt, encoding="utf-8")

    result = TextToCadResult(
        case_id=case.case_id,
        ok=False,
        expected_outcome=case.expected_outcome,
        case_dir=case_dir,
        logs=logs,
    )
    result.logs_path = case_dir / "logs.jsonl"

    _log_event(logs, case.case_id, "prompt_received", "case_start")

    try:
        # ── Step 1: Level-1 Routing ──
        _log_event(logs, case.case_id, "routing_start", "building_routing_prompt")

        from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
            build_level1_routing_prompt, build_level1_tool, get_level1_tool_choice,
        )
        from seekflow_engineering_tools.generative_cad.dialects.registry import (
            export_dialect_catalog,
        )
        from seekflow_engineering_tools.config import EngineeringToolsConfig

        dialect_catalog = export_dialect_catalog()
        routing_prompt = build_level1_routing_prompt(
            user_request=case.prompt,
            dialect_catalog=dialect_catalog,
        )

        if skip_llm:
            result.error = "LLM calls skipped (skip_llm=True)"
            result.error_stage = "routing"
            result.error_code = "llm_skipped"
            return result

        _log_event(logs, case.case_id, "routing_start", "calling_llm_routing")

        # Use function calling (enum-constrained) instead of json_object
        route_plan = _call_deepseek_tool(
            client,
            system_prompt=routing_prompt["system"],
            user_prompt=routing_prompt["user"],
            tools=[build_level1_tool()],
            tool_choice=get_level1_tool_choice(),
        )

        result.route_plan = route_plan
        (case_dir / "route_plan.json").write_text(
            json.dumps(route_plan, indent=2, ensure_ascii=False), encoding="utf-8")

        route_decision = route_plan.get("route_decision", "unsupported")
        result.actual_route = route_decision

        _log_event(logs, case.case_id, "routing_result", "route_decision",
                   ok=True, details={"route": route_decision})

        # ── Handle unsupported route ──
        if route_decision == "unsupported":
            result.ok = False
            result.error = f"Route decision: unsupported. Reasons: {route_plan.get('unsupported_capabilities', [])}"
            result.error_stage = "routing"
            result.error_code = "unsupported"
            _log_event(logs, case.case_id, "routing_result", "unsupported",
                       ok=False, details=route_plan)
            _write_summary(result, case_dir)
            _write_logs(logs, result.logs_path)
            return result

        # ── Handle deterministic primitive route ──
        if route_decision == "deterministic_primitive":
            return _run_primitive_route(case, case_dir, route_plan, logs, result)

        # ── Handle generative_cad_ir route ──
        if route_decision == "generative_cad_ir":
            return _run_generative_route(case, case_dir, route_plan, logs, result,
                                         client, api_key)

        # Unknown route
        result.ok = False
        result.error = f"Unknown route decision: {route_decision}"
        result.error_stage = "routing"
        result.error_code = "unknown_route"
        _log_event(logs, case.case_id, "routing_result", "unknown_route",
                   ok=False)
        _write_summary(result, case_dir)
        _write_logs(logs, result.logs_path)
        return result

    except Exception as exc:
        result.ok = False
        result.error = f"{type(exc).__name__}: {exc}"
        result.error_stage = result.error_stage or "unknown"
        result.error_code = result.error_code or "exception"
        tb = traceback.format_exc()
        _log_event(logs, case.case_id, result.error_stage, "exception",
                   ok=False, details={"error": str(exc), "traceback": tb[-2000:]})
        (case_dir / "errors.json").write_text(
            json.dumps({"error": str(exc), "traceback": tb}, indent=2), encoding="utf-8")
        _write_summary(result, case_dir)
        _write_logs(logs, result.logs_path)
        return result


def _run_primitive_route(
    case: TextToCadCase,
    case_dir: Path,
    route_plan: dict,
    logs: list[dict],
    result: TextToCadResult,
) -> TextToCadResult:
    """Run the deterministic primitive build path."""
    from seekflow_engineering_tools.config import EngineeringToolsConfig

    config = EngineeringToolsConfig(workspace_root=str(case_dir.parent))

    primitive_name = route_plan.get("selected_primitive", "")
    if not primitive_name and case.expected_primitive:
        primitive_name = case.expected_primitive

    # Build CADPartSpec for the primitive
    params = _extract_primitive_params(case.prompt, primitive_name)
    spec = {
        "name": case.case_id,
        "units": "mm",
        "target_backend": ["cadquery"],
        "features": [{
            "id": "feat_1",
            "type": "primitive",
            "primitive_name": primitive_name or "involute_spur_gear",
            "parameters": params,
        }],
        "validation": {
            "expected_body_count": 1,
        },
        "outputs": {
            "step": True,
            "native": True,
        },
    }
    # Add gear-specific validation if applicable
    if "teeth" in params:
        spec["validation"]["expected_tooth_count"] = params["teeth"]
    if "module_mm" in params and "teeth" in params:
        spec["validation"]["expected_pitch_diameter_mm"] = params["module_mm"] * params["teeth"]
        spec["validation"]["expected_outer_diameter_mm"] = params["module_mm"] * (params["teeth"] + 2)
    if "face_width_mm" in params:
        spec["validation"]["expected_face_width_mm"] = params["face_width_mm"]
    if "bore_dia_mm" in params:
        spec["validation"]["expected_bore_diameter_mm"] = params["bore_dia_mm"]
    if "pressure_angle_deg" in params:
        spec["validation"]["tolerance_mm"] = 0.5

    (case_dir / "cad_part_spec.json").write_text(
        json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")

    _log_event(logs, case.case_id, "build_start", "primitive_build")

    from seekflow_engineering_tools.cadquery_backend.builder import (
        build_cadquery_from_cad_ir,
    )
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    # Validate and normalize spec through CADPartSpec
    cad_spec = CADPartSpec.model_validate(spec)

    out_step = str(case_dir / "output.step")
    build_result = build_cadquery_from_cad_ir(
        spec=cad_spec,
        config=config,
        out_step=out_step,
        inspect=True,
    )

    result.ok = build_result.get("ok", False)
    if result.ok:
        result.step_path = Path(out_step)
        result.metadata_path = _find_metadata(case_dir)
        result.artifact_path = _find_artifact(case_dir)

        _log_event(logs, case.case_id, "step_export", "step_created",
                   ok=result.step_exists)
        _log_event(logs, case.case_id, "import_gate_result", "primitive_ok", ok=True)
    else:
        result.error = build_result.get("error", "Primitive build failed")
        result.error_stage = "build_start"
        result.error_code = "primitive_build_failed"
        _log_event(logs, case.case_id, "build_start", "primitive_failed",
                   ok=False, details={"error": result.error})

    _write_summary(result, case_dir)
    _write_logs(logs, result.logs_path)
    return result


def _run_generative_route(
    case: TextToCadCase,
    case_dir: Path,
    route_plan: dict,
    logs: list[dict],
    result: TextToCadResult,
    client,
    api_key: str = "",
) -> TextToCadResult:
    """Run the generative CAD-IR build path.

    After the LLM generates a RawGcadDocument, we run it through the parse layer
    and, if parse fails, feed the structured errors back to the LLM for self-correction.
    This gives the LLM up to MAX_SELF_CORRECT_ATTEMPTS tries to fix its own output
    before we declare failure.
    """
    from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
        build_level2_authoring_prompt, build_level2_tool, get_level2_tool_choice,
    )
    from seekflow_engineering_tools.generative_cad.dialects.registry import (
        DIALECT_REGISTRY,
    )
    from seekflow_engineering_tools.generative_cad.skills.schemas import (
        DialectSelectionPlan,
    )
    from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
    from seekflow_engineering_tools.config import EngineeringToolsConfig

    config = EngineeringToolsConfig(workspace_root=str(case_dir.parent))
    MAX_SELF_CORRECT_ATTEMPTS = 2

    # Load contracts for selected dialects
    selection_plan = DialectSelectionPlan.model_validate(route_plan)
    contracts = {}
    for sd in selection_plan.selected_dialects:
        dialect = DIALECT_REGISTRY.get(sd.dialect)
        if dialect is not None:
            contracts[sd.dialect] = dialect.contract()

    _log_event(logs, case.case_id, "dialect_contract_loaded", "contracts_loaded",
               ok=True, details={"dialects": list(contracts.keys())})

    # ── Step 2 & 3: Level-2 Authoring with self-correction loop ──

    authoring_prompt = build_level2_authoring_prompt(
        user_request=case.prompt,
        selection_plan=selection_plan,
        contracts=contracts,
    )

    # Build L2 tool once (schema is large, reuse across attempts)
    l2_tool = build_level2_tool(contracts=contracts)
    l2_tool_choice = get_level2_tool_choice()

    raw_gcad: dict | None = None
    last_parse_error = ""
    total_attempts = 0

    for attempt in range(1 + MAX_SELF_CORRECT_ATTEMPTS):
        total_attempts = attempt + 1

        if attempt == 0:
            # First attempt: normal Level-2 authoring
            _log_event(logs, case.case_id, "authoring_start", "calling_llm_authoring")
            user_message = authoring_prompt["user"]
        else:
            # Self-correction attempt: feed parse errors back to LLM
            _log_event(logs, case.case_id, "repair_attempt",
                       f"self_correct_{attempt}",
                       ok=False, details={"last_error": last_parse_error[:500]})
            result.repair_attempts = attempt

            user_message = _build_self_correction_prompt(
                user_request=case.prompt,
                previous_output=json.dumps(raw_gcad, indent=2, ensure_ascii=False),
                parse_errors=last_parse_error,
                contracts=contracts,
            )

        # Use function calling (enum-constrained) for schema compliance
        raw_gcad = _call_deepseek_tool(
            client,
            system_prompt=authoring_prompt["system"],
            user_prompt=user_message,
            tools=[l2_tool],
            tool_choice=l2_tool_choice,
        )

        result.raw_gcad = raw_gcad
        (case_dir / "raw_gcad.json").write_text(
            json.dumps(raw_gcad, indent=2, ensure_ascii=False), encoding="utf-8")

        _log_event(logs, case.case_id, "parse_result",
                   f"self_correct_attempt_{attempt}" if attempt > 0 else "initial_parse",
                   ok=True, details={"document_id": raw_gcad.get("document_id", "")})

        # ── Pre-flight: parse the document locally to catch parse errors early ──
        parse_result = parse_raw_gcad_document(raw_gcad)
        if parse_result.ok:
            _log_event(logs, case.case_id, "parse_result", "parse_passed", ok=True)
            break  # Document is parse-valid, proceed to builder

        # Parse failed — format errors for the LLM
        last_parse_error = "; ".join(
            f"[{i.code}] {i.message}" for i in parse_result.issues
        )
        _log_event(logs, case.case_id, "parse_result", "parse_failed",
                   ok=False, details={"errors": last_parse_error})

        if attempt >= MAX_SELF_CORRECT_ATTEMPTS:
            # Exhausted all attempts — fail with the last error
            result.ok = False
            result.error = f"RawGcadDocument parse failed after {total_attempts} LLM attempts: {last_parse_error}"
            result.error_stage = "parse"
            result.error_code = "parse_failed_after_self_correction"
            _log_event(logs, case.case_id, "parse_result", "parse_exhausted",
                       ok=False, details={"attempts": total_attempts})
            _write_summary(result, case_dir)
            _write_logs(logs, result.logs_path)
            return result

    # ── Step 4: Build (parse passed, now do full validation + canonicalize + run) ──
    _log_event(logs, case.case_id, "build_start", "generative_build")

    from seekflow_engineering_tools.generative_cad.builder import (
        build_generative_cad_model,
    )

    out_step = str(case_dir / "output.step")
    build_result = build_generative_cad_model(
        spec=raw_gcad,
        config=config,
        out_step=out_step,
        inspect=True,
        strict_inspection=True,
    )

    result.ok = build_result.get("ok", False)

    if result.ok:
        result.step_path = Path(out_step)
        result.metadata_path = _find_metadata(case_dir)
        result.artifact_path = _find_artifact(case_dir)

        _log_event(logs, case.case_id, "step_export", "step_created",
                   ok=result.step_exists)
        _log_event(logs, case.case_id, "metadata_written", "metadata_created",
                   ok=result.metadata_exists)
        _log_event(logs, case.case_id, "import_gate_result", "generative_ok", ok=True)

        if result.metadata_path:
            try:
                meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
                validation = meta.get("validation", {})
                result.validation_stages = {
                    k: v.get("ok", False) if isinstance(v, dict) else False
                    for k, v in validation.items()
                }
            except Exception:
                pass
    else:
        result.error = build_result.get("error", "Generative build failed")
        result.error_stage = "build_start"
        result.error_code = "generative_build_failed"

        metrics = build_result.get("metrics", {})
        if isinstance(metrics, dict):
            validation = metrics.get("validation", {})
            if isinstance(validation, dict) and not validation.get("ok", True):
                result.error_stage = "validation"
                issues = validation.get("issues", [])
                if issues:
                    result.error_code = issues[0].get("code", "validation_error")
                    result.error = issues[0].get("message", result.error)

        _log_event(logs, case.case_id, "build_start", "generative_failed",
                   ok=False, details={"error": result.error})

    _write_summary(result, case_dir)
    _write_logs(logs, result.logs_path)
    return result


def _build_self_correction_prompt(
    user_request: str,
    previous_output: str,
    parse_errors: str,
    contracts: dict,
) -> str:
    """Build a self-correction prompt that asks the LLM to fix parse errors."""
    dialect_list = list(contracts.keys())
    return (
        f"Your previous RawGcadDocument output had parse errors.\n\n"
        f"User request: {user_request}\n\n"
        f"Parse errors:\n{parse_errors}\n\n"
        f"Available dialects (use only these exact names): {', '.join(dialect_list)}\n\n"
        f"Your previous output was:\n{previous_output[:3000]}\n\n"
        f"Please fix the errors and output a corrected, complete RawGcadDocument JSON.\n"
        f"Make sure ALL required fields are present:\n"
        f"  schema_version, document_id, part_name, units, trust_level,\n"
        f"  selected_dialects, components, nodes, constraints, safety\n"
        f"Output ONLY valid JSON — no markdown, no prose, no comments."
    )


def _extract_primitive_params(prompt: str, primitive_name: str) -> dict:
    """Extract primitive parameters from natural language prompt using simple regex.

    This is a best-effort parser. For production use, the LLM should generate
    the full CADPartSpec. This function handles the common case of gear params.
    """
    import re
    params: dict = {}

    if primitive_name == "involute_spur_gear":
        # Extract common gear parameters from Chinese prompts
        # Supports: "齿数 20", "20 齿", "20齿"
        teeth_match = re.search(r'齿数\s*(\d+)', prompt)
        if not teeth_match:
            teeth_match = re.search(r'(\d+)\s*齿', prompt)
        if teeth_match:
            params["teeth"] = int(teeth_match.group(1))

        module_match = re.search(r'模数\s*(\d+\.?\d*)', prompt)
        if module_match:
            params["module_mm"] = float(module_match.group(1))

        pa_match = re.search(r'压力角\s*(\d+\.?\d*)', prompt)
        if pa_match:
            params["pressure_angle_deg"] = float(pa_match.group(1))

        width_match = re.search(r'齿宽\s*(\d+\.?\d*)', prompt)
        if width_match:
            params["face_width_mm"] = float(width_match.group(1))

        # Supports: "中心孔 8", "中心孔直径 8", "孔径 8"
        bore_match = re.search(r'(?:中心孔(?:直径)?|孔径)\s*(\d+\.?\d*)', prompt)
        if bore_match:
            params["bore_dia_mm"] = float(bore_match.group(1))

    return params


def _find_metadata(case_dir: Path) -> Path | None:
    """Find metadata JSON file in case directory or workspace."""
    for pattern in ["**/*metadata*.json", "**/*.metadata.json", "**/metadata.json"]:
        found = list(case_dir.glob(pattern))
        if found:
            return found[0]
    return None


def _find_artifact(case_dir: Path) -> Path | None:
    """Find artifact JSON file in case directory or workspace."""
    for pattern in ["**/*artifact*.json", "**/artifact.json"]:
        found = list(case_dir.glob(pattern))
        if found:
            return found[0]
    return None


def _write_summary(result: TextToCadResult, case_dir: Path) -> None:
    """Write case summary JSON."""
    summary = {
        "case_id": result.case_id,
        "ok": result.ok,
        "expected_outcome": result.expected_outcome,
        "actual_route": result.actual_route,
        "step_path": str(result.step_path) if result.step_path else None,
        "metadata_path": str(result.metadata_path) if result.metadata_path else None,
        "artifact_path": str(result.artifact_path) if result.artifact_path else None,
        "import_gate_ok": result.ok,
        "validation_stages": result.validation_stages,
        "repair_attempts": result.repair_attempts,
        "warnings": result.warnings,
        "error_stage": result.error_stage,
        "error_code": result.error_code,
        "error": result.error,
    }
    (case_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_logs(logs: list[dict], logs_path: Path) -> None:
    """Write structured logs as JSONL."""
    with open(logs_path, "w", encoding="utf-8") as f:
        for entry in logs:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
