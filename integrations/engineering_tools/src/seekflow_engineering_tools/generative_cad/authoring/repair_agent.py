"""RepairAgent — 带完整 dialect contract 知识的 LLM 修复循环。

当 AutoFixer 无法修复所有验证错误时，RepairAgent:
  1. 将验证错误 + 完整 OperationSpec contract 发给 LLM
  2. LLM 返回局部修复后的 RawGcadDocument
  3. 重新验证
  4. 最多 3 轮
"""

from __future__ import annotations
import json, os
from typing import Any


def build_repair_prompt(
    raw_doc: dict,
    validation_issues: list,
    dialect_registry,
) -> str:
    """构建修复 prompt: 验证错误 + 完整 contract。"""
    # 提取相关 dialect 的 contract
    dialects_in_doc = set()
    for node in raw_doc.get("nodes", []):
        dialects_in_doc.add(node.get("dialect", ""))
    for sd in raw_doc.get("selected_dialects", []):
        dialects_in_doc.add(sd.get("dialect", ""))

    contract_lines = []
    for did in sorted(dialects_in_doc):
        d = dialect_registry.get(did)
        if d is None:
            continue
        contract_lines.append(f"=== Dialect: {did} v{d.version} ===")
        contract_lines.append(f"Phase order: {' → '.join(d.phase_order)}")
        for (op_name, _), spec in d.op_specs().items():
            ps = spec.params_model.model_json_schema()
            props = ps.get("properties", {})
            req_list = ps.get("required", [])
            param_strs = []
            for pname, pinfo in props.items():
                req = "REQUIRED" if pname in req_list else "optional"
                ptype = pinfo.get("type", "?")
                desc = pinfo.get("description", "")
                ref = pinfo.get("$ref", "")
                enum_vals = pinfo.get("enum", [])
                if ref:
                    ref_name = ref.split("/")[-1]
                    nested = ps.get("$defs", {}).get(ref_name, {})
                    nested_props = nested.get("properties", {})
                    fields = ", ".join(f"{k}:{v.get('type','?')}" for k, v in nested_props.items())
                    param_strs.append(f"{pname}=[{req}] list of {{{fields}}}")
                elif enum_vals:
                    param_strs.append(f"{pname}=one of {enum_vals} [{req}]")
                else:
                    param_strs.append(f"{pname}:{ptype} [{req}]")
            contract_lines.append(
                f"  op='{op_name}' v='{spec.op_version}' phase='{spec.phase}' "
                f"inputs={list(spec.input_types)} outputs={list(spec.output_types)}"
            )
            contract_lines.append(f"    params: {' | '.join(param_strs)}")
        contract_lines.append("")

    issues_str = "\n".join(
        f"  [{i.get('code','?')}] {i.get('message','?')}"
        for i in validation_issues[:20]
    )

    return f"""You are repairing a RawGcadDocument that failed validation.

VALIDATION ERRORS:
{issues_str}

CURRENT RawGcadDocument:
{json.dumps(raw_doc, indent=2, ensure_ascii=False)}

COMPLETE DIALECT CONTRACTS (use ONLY these exact names and fields):
{chr(10).join(contract_lines)}

TASK: Fix ALL validation errors by outputting a corrected RawGcadDocument.
- Do NOT change schema_version, safety, constraints structure, or trust_level.
- Do NOT invent new operations or field names.
- Use EXACTLY the field names shown in the contracts above.
- Keep the graph structure but fix the parameter names, values, and wiring.
- revolve_profile ALWAYS needs 'axis' and 'profile_stations'.
- Output name for solids must be 'body', for frames must be 'outer_frame'.
- selected_dialects version must match the dialect version.
- ALL 7 safety flags must be explicitly true.
"""


def call_deepseek_repair(system: str, user: str, tool_schema: dict, model: str = "deepseek-v4-pro") -> dict:
    """调用 DeepSeek 进行修复。"""
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com/beta",
    )
    tools = [{
        "type": "function",
        "function": {"name": "gcad", "strict": True, "parameters": tool_schema},
    }]
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "gcad"}},
        timeout=120,
        extra_body={"thinking": {"type": "disabled"}},
    )
    msg = response.choices[0].message
    if not msg.tool_calls:
        raise RuntimeError("No tool call in repair")
    return json.loads(msg.tool_calls[0].function.arguments)


def repair_with_llm(
    raw_doc: dict,
    validation_report,
    dialect_registry,
    max_rounds: int = 3,
) -> dict | None:
    """LLM 修复循环。返回修复后的 doc，或 None 表示放弃。"""
    from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
    from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
    from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix

    issues = [
        {"code": i.code, "message": i.message, "path": i.path}
        for i in (validation_report.issues if validation_report else [])
    ]

    for round_num in range(max_rounds):
        prompt = build_repair_prompt(raw_doc, issues, dialect_registry)
        system = "You are a G-CAD IR repair specialist. You fix validation errors in RawGcadDocument JSON."

        try:
            raw_schema = RawGcadDocument.model_json_schema()
            tool_schema = to_deepseek_strict_schema(raw_schema)
            repaired = call_deepseek_repair(system, prompt, tool_schema)
        except Exception:
            continue

        # 应用自动修复
        repaired = auto_fix(repaired, dialect_registry)

        # 补全缺失字段
        if repaired.get("llm_validation_hints") is None:
            repaired["llm_validation_hints"] = {}
        if "units" not in repaired:
            repaired["units"] = "mm"
        if "trust_level" not in repaired:
            repaired["trust_level"] = "reference_geometry"
        if "safety" not in repaired:
            repaired["safety"] = {k: True for k in [
                "non_flight_reference_only", "not_airworthy", "not_certified",
                "not_for_manufacturing", "not_for_installation",
                "no_structural_validation", "no_life_prediction",
            ]}
        if "constraints" not in repaired:
            repaired["constraints"] = {
                "require_step_file": True, "require_metadata_sidecar": True,
                "require_closed_solid": True, "expected_body_count": 1,
            }

        # 重新验证
        try:
            doc = RawGcadDocument.model_validate(repaired)
        except Exception as e:
            issues = [{"code": "pydantic_error", "message": str(e)}]
            continue

        canonical, report = validate_and_canonicalize(doc)
        if canonical and report.ok:
            return repaired

        issues = [
            {"code": i.code, "message": i.message, "path": i.path}
            for i in (report.issues if report else [])
        ]

    return None
