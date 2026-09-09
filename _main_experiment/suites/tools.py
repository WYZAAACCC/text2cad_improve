"""Tool-planning suite: 160 tasks x fixed/MCP/llm-code interfaces x 5 runs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..adapters import call_mcp_tool, load_mcp_tool_registry
from ..config import ExperimentConfig, LlmConfig
from ..llm import OpenAICompatToolClient
from ..schemas import TaskSpec
from .base import ensure_golden, stamp_record, suite_root

_CORE_TOOLS = (
    "check_solid_validity", "check_degenerate_geometry", "count_fir_tree_slots",
    "measure_disc_dimensions", "measure_fir_tree_slot_profile",
    "validate_slot_step_roundtrip", "check_slot_pitch_and_ligament",
    "check_adjacent_feature_clearance", "validate_slot_pattern_periodicity",
)


def _new_tool_catalog() -> list[dict[str, Any]]:
    return [
        {"name": "measure_hub_radial_height", "description": "测量轮毂径向高度 hub_radius-bore_radius"},
        {"name": "measure_rim_radial_height", "description": "测量轮缘径向高度 rim_radius-rim_web_junction"},
        {"name": "measure_web_radial_length", "description": "测量腹板径向长度 rim_web_junction-hub_radius"},
        {"name": "measure_hub_half_thickness", "description": "测量轮毂半厚"},
        {"name": "measure_rim_half_thickness", "description": "测量轮缘半厚"},
        {"name": "measure_web_inner_half", "description": "测量腹板内半厚"},
        {"name": "measure_web_outer_half", "description": "测量腹板外半厚"},
        {"name": "count_cooling_holes", "description": "统计冷却孔数量"},
        {"name": "count_lightening_holes", "description": "统计减重孔数量"},
        {"name": "count_grooves", "description": "统计环槽数量"},
        {"name": "measure_groove_depth", "description": "测量环槽径向深度"},
        {"name": "measure_groove_width", "description": "测量环槽轴向宽度"},
        {"name": "measure_slot_distribution_radius", "description": "测量榫槽分布半径"},
        {"name": "measure_slot_circumferential_pitch", "description": "测量榫槽周向节距"},
        {"name": "count_boolean_cuts", "description": "统计布尔切除操作数量"},
        {"name": "count_patterns", "description": "统计圆周阵列数量"},
        {"name": "check_closed_profile", "description": "检查所有草图轮廓是否闭合"},
        {"name": "check_unique_node_ids", "description": "检查节点 id 是否唯一"},
        {"name": "check_sketch_plane_valid", "description": "检查草图平面是否合法"},
        {"name": "check_assembly_root_solid", "description": "检查装配根节点输出是否为 solid"},
    ]


def _ir(base_dir: str) -> dict[str, Any]:
    return json.loads((Path(base_dir) / "raw_fixed.json").read_text(encoding="utf-8"))


def _model_feature_summary(base_dir: str) -> str:
    """One-line feature summary for the verification agent (environment perception)."""
    try:
        ir = _ir(base_dir)
        kinds = {c.get("kind_hint") for c in ir.get("components", [])}
        names = {
            "turbine_disc": "盘体",
            "fir_tree_cutter": "榫槽",
            "hole_cutter": "孔",
            "groove_cutter": "环槽",
        }
        feats = [names[k] for k in ("turbine_disc", "fir_tree_cutter",
                                    "hole_cutter", "groove_cutter") if k in kinds]
        return "该模型包含：" + "、".join(feats) if feats else "该模型特征未知"
    except Exception:
        return "该模型特征未知"


def _infer_capabilities_from_code(code: str) -> list[str]:
    """Infer implemented check/measure capabilities from code text (auditable)."""
    low = (code or "").lower()
    caps: list[str] = []
    if "cadquery" in low or "import cq" in low or "importstep" in low:
        if any(k in low for k in ("solid", "volume", "val()", "isvalid")):
            caps.append("check_solid_validity")
        if any(k in low for k in ("boundingbox", "bbox", "xlen", "diameter",
                                  "thickness", "dimension")):
            caps.append("measure_disc_dimensions")
        if any(k in low for k in ("slot", "fir_tree", "teeth", "fir")):
            caps.append("count_fir_tree_slots")
    return caps


def _run_new_tool(name: str, base_dir: str) -> dict[str, Any]:
    ir = _ir(base_dir)
    nodes = ir.get("nodes", [])
    comps = {c["id"]: (c.get("kind_hint") or "") for c in ir.get("components", [])}
    feats = [n.get("component") for n in nodes if str(n.get("component")).startswith("feat_")]
    disc = next((n for n in nodes if n.get("component") == "disc_body"
                 and n.get("op") == "add_polyline"), None)
    pts = (disc or {}).get("params", {}).get("points", [])
    distinct_x = sorted({p.get("x_mm", 0) for p in pts}) if pts else []
    distinct_y = sorted({p.get("y_mm", 0) for p in pts}) if pts else []
    if len(distinct_x) >= 4:
        bore, hub, junc, rim = distinct_x[0], distinct_x[1], distinct_x[2], distinct_x[-1]
    else:
        bore = hub = junc = rim = None
    ys_abs = sorted({abs(p.get("y_mm", 0)) for p in pts}) if pts else []
    patterns = [n for n in nodes if n.get("op") == "circular_pattern_component"]
    slot_pat = next((n for n in patterns
                     if str(n.get("inputs") or "").find("cutter") >= 0), None) or (patterns[0] if patterns else None)
    slot_radius = (slot_pat or {}).get("params", {}).get("radius_mm")
    slot_count = (slot_pat or {}).get("params", {}).get("count")
    grooves = [n for n in nodes if "groove" in str(n.get("component"))
               and n.get("op") == "add_polyline"]
    groove_xs = [p.get("x_mm", 0) for g in grooves for p in g.get("params", {}).get("points", [])]
    groove_ys = [p.get("y_mm", 0) for g in grooves for p in g.get("params", {}).get("points", [])]
    comps_with_poly = {n.get("component") for n in nodes if n.get("op") == "add_polyline"}
    lookup = {
        "measure_hub_radial_height": (hub - bore) if (hub is not None and bore is not None) else None,
        "measure_rim_radial_height": (rim - junc) if (rim is not None and junc is not None) else None,
        "measure_web_radial_length": (junc - hub) if (junc is not None and hub is not None) else None,
        "measure_hub_half_thickness": ys_abs[-1] if ys_abs else None,
        "measure_rim_half_thickness": ys_abs[2] if len(ys_abs) >= 3 else None,
        "measure_web_inner_half": ys_abs[1] if len(ys_abs) >= 2 else None,
        "measure_web_outer_half": ys_abs[0] if ys_abs else None,
        "count_cooling_holes": sum(1 for c in feats if "cl_" in str(c)),
        "count_lightening_holes": sum(1 for c in feats if c == "feat_lh"),
        "count_grooves": len(grooves),
        "measure_groove_depth": (max(groove_xs) - min(groove_xs)) if groove_xs else None,
        "measure_groove_width": (max(groove_ys) - min(groove_ys)) if groove_ys else None,
        "measure_slot_distribution_radius": slot_radius,
        "measure_slot_circumferential_pitch": (
            round(2 * 3.141592653589793 * float(slot_radius) / int(slot_count), 4)
            if slot_radius is not None and slot_count else None),
        "count_boolean_cuts": sum(1 for n in nodes if n.get("op") == "boolean_cut"),
        "count_patterns": len(patterns),
        "check_closed_profile": all(
            "close_profile" in {n.get("op") for n in nodes if n.get("component") == c}
            for c in comps_with_poly),
        "check_unique_node_ids": len({n.get("id") for n in nodes}) == len(nodes),
        "check_sketch_plane_valid": all(n.get("params", {}).get("plane") in ("XZ", "XY")
                                        for n in nodes if n.get("op") == "create_2d_sketch"),
        "check_assembly_root_solid": any(str(c) == "__assembly__" for c in comps),
    }
    value = lookup.get(name)
    return {"ok": value is not None, "value": value, "tool": name}


def _tool_catalog() -> dict[str, dict[str, Any]]:
    cat = dict(load_mcp_tool_registry())
    for t in _new_tool_catalog():
        cat[t["name"]] = {"name": t["name"], "description": t["description"],
                          "input_schema": {}, "handler": None}
    return cat


def _call_tool(name: str, base_dir: str, *, allow_new: bool = True) -> dict[str, Any]:
    reg = load_mcp_tool_registry()
    if name in reg:
        return reg[name]["handler"]({"base_dir": base_dir})
    if allow_new:
        return _run_new_tool(name, base_dir)
    return {"ok": False, "error": f"tool not registered: {name}"}


def build_tasks(tasks: list[TaskSpec]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    new_tools = _new_tool_catalog()
    new_names = [t["name"] for t in new_tools]
    new_goals = {t["name"]: t["description"] for t in new_tools}
    for tidx, task in enumerate(tasks):
        has_slot = bool((task.normalized_params.get("slots") or 0) > 0
                        or task.gold.slot_reference is not None)
        multi_seq = (["check_solid_validity", "count_fir_tree_slots"] if has_slot
                     else ["check_solid_validity", "measure_disc_dimensions"])
        categories = [
            ("single", [task.gold.acceptance.require_step_file and "check_solid_validity" or "check_solid_validity"], False),
            ("multi", multi_seq, False),
            ("anomaly", ["measure_disc_dimensions"], True),
            ("new", [new_names[tidx % len(new_names)]], True),
        ]
        for cat, seq, is_new in categories:
            goal = ""
            if cat == "new":
                goal = new_goals.get(seq[0], "使用新增测量工具完成测量")
            out.append({
                "tool_task_id": f"{task.task_id}_TOOL_{cat}",
                "category": cat,
                "task_id": task.task_id,
                "tool_sequence": seq,
                "goal": goal,
                "expect_anomaly": is_new and cat == "anomaly",
                "new_tool": is_new and cat == "new",
            })
    return out


def _run_fixed(task: dict[str, Any], base_dir: str) -> dict[str, Any]:
    results = [_call_tool(t, base_dir, allow_new=False)
               for t in task["tool_sequence"]]
    all_ok = all(r.get("ok") for r in results)
    return {
        "tool_task_id": task["tool_task_id"], "category": task["category"],
        "selected": set(task["tool_sequence"]),
        "ordered_selected": list(task["tool_sequence"]),
        "expected": set(task["tool_sequence"]),
        "binding_ok": True, "multi_complete": all_ok,
        "result_ok": all_ok, "new_tool_called": False,
        "unregistered_tool": any(t not in load_mcp_tool_registry()
                                 for t in task["tool_sequence"]),
    }


def _run_mcp_agent(task: dict[str, Any], base_dir: str, client: Any,
                   llm: LlmConfig) -> dict[str, Any]:
    catalog = _tool_catalog()
    registered = set(load_mcp_tool_registry())
    groups = {
        "实体与几何验证": [k for k in catalog
                        if k.startswith("check_") or k.startswith("validate_")],
        "现有测量与计数工具": [k for k in catalog
                          if (k.startswith("measure_") or k.startswith("count_"))
                          and k in registered],
        "新增测量工具（训练后注册）": [k for k in catalog if k not in registered],
    }
    desc_parts = []
    for group, names in groups.items():
        desc_parts.append(f"[{group}]")
        for k in names:
            desc_parts.append(f"- {k}: {catalog[k]['description']}")
    desc = "\n".join(desc_parts)
    goal = task.get("goal") or {
        "single": "验证生成模型是否为单一有效封闭实体",
        "multi": "同时验证实体有效性以及关键特征（榫槽数量或盘体尺寸）",
        "anomaly": "测量盘体关键尺寸以发现异常",
        "new": "使用训练后新增的专用测量工具完成测量",
    }.get(task["category"], "完成对应工程验证")
    extra_rule = ""
    if task["category"] == "multi":
        extra_rule = ("该任务必须输出至少两个工具，且第一个必须是实体与几何验证类工具，"
                      "第二个根据模型特征选择测量/计数工具。")
    if task["category"] == "anomaly":
        extra_rule = "该任务使用现有测量工具检查盘体尺寸是否异常。"
    if task["category"] == "single":
        extra_rule = "该任务只需选择 1 个实体与几何验证工具。"
    if task["category"] == "new":
        extra_rule = ("该任务必须从[新增测量工具（训练后注册）]中选择 1 个工具，"
                      "必须调用训练后新增工具，不得回退到现有测量工具。")
    lines = [
        f"当前任务：{task['tool_task_id']}",
        f"任务目标：{goal}",
        f"模型特征：{_model_feature_summary(base_dir)}",
    ]
    if extra_rule:
        lines.append(f"额外要求：{extra_rule}")
    lines.append(f"可用工具目录：\n{desc}")
    lines.append(
        "请先简述选择依据（reasoning），再输出与任务目标匹配的**工具序列**（一个或多个）。"
        "工具必须与模型特征匹配：模型无榫槽时不得使用榫槽计数工具。")
    lines.append(
        f"输出 JSON：{{\"reasoning\":\"...\",\"tools\":[{{\"tool\":\"工具名\","
        f"\"args\":{{\"base_dir\":\"{base_dir}\"}}}}]}}")
    base_prompt = "\n".join(lines)
    schema = {"type": "object", "properties": {
        "tools": {"type": "array",
                  "items": {"type": "object",
                            "properties": {"tool": {"type": "string"},
                                           "args": {"type": "object"}},
                            "required": ["tool"]}},
        "reasoning": {"type": "string"}}, "required": ["tools"]}
    selected: set[str] = set()
    outs: list[dict[str, Any]] = []
    last_error = ""
    attempts = 0
    for attempt in range(2):
        attempts = attempt + 1
        prompt = base_prompt
        if last_error:
            prompt += ("\n\n上一次工具执行失败，请根据错误重新选择工具，"
                       "不要重复同一个失败工具。失败信息：" + last_error)
        try:
            result = client.call_strict_tool(
                messages=[{"role": "user", "content": prompt}],
                tool_name="emit_tool_choice", tool_description="选择工具",
                tool_schema=schema, config=llm,
            )
            choice = result.arguments
            tools = choice.get("tools") or []
            if not tools and choice.get("tool"):
                tools = [{"tool": choice["tool"], "args": choice.get("args") or {}}]
        except Exception as exc:  # noqa: BLE001
            return {"tool_task_id": task["tool_task_id"], "category": task["category"],
                    "selected": set(), "ordered_selected": [],
                    "expected": set(task["tool_sequence"]),
                    "binding_ok": False, "multi_complete": False, "result_ok": False,
                    "new_tool_called": False, "error": str(exc)[:200]}
        selected = set()
        outs = []
        ordered_selected: list[str] = []
        binding_ok = True
        for item in tools:
            tool = item.get("tool", "")
            if not tool:
                continue
            args = item.get("args")
            if not isinstance(args, dict) or str(args.get("base_dir", "")) != base_dir:
                binding_ok = False
            selected.add(tool)
            ordered_selected.append(tool)
            outs.append(_call_tool(tool, base_dir))
        if all(o.get("ok") for o in outs) and outs:
            break
        failed = [o for o in outs if not o.get("ok")]
        last_error = "; ".join(
            f"{o.get('tool', '?')}: {o.get('error') or o.get('reason') or 'failed'}"
            for o in failed)[:300]
    all_ok = bool(outs) and all(o.get("ok") for o in outs)
    expected = set(task["tool_sequence"])
    complete = bool(outs) and expected.issubset(selected) and all_ok
    return {
        "tool_task_id": task["tool_task_id"], "category": task["category"],
        "selected": selected, "ordered_selected": ordered_selected,
        "expected": expected,
        "binding_ok": binding_ok,
        "multi_complete": complete,
        "result_ok": all_ok,
        "new_tool_called": any(
            t in set(task["tool_sequence"])
            and t not in load_mcp_tool_registry()
            and o.get("ok")
            for t, o in zip(ordered_selected, outs)),
        "attempts": attempts,
    }


def _run_python_utf8(code: str, *, timeout: float = 60.0):
    """Execute code as a UTF-8 temp module with full env (avoids GBK sandbox issues)."""
    import os as _os
    import subprocess
    import tempfile

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False,
                                      encoding="utf-8")
    try:
        tmp.write(code)
        tmp.close()
        return subprocess.run(
            [_os.sys.executable, tmp.name],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, shell=False,
            env=dict(_os.environ),
            cwd=tempfile.gettempdir(),
        )
    finally:
        try:
            _os.unlink(tmp.name)
        except Exception:
            pass


def _run_llm_code(task: dict[str, Any], base_dir: str, client: Any,
                  llm: LlmConfig) -> dict[str, Any]:
    summary = _model_feature_summary(base_dir)
    catalog = _tool_catalog()
    registered = set(load_mcp_tool_registry())
    groups = {
        "实体与几何验证": [k for k in catalog
                        if k.startswith("check_") or k.startswith("validate_")],
        "现有测量与计数工具": [k for k in catalog
                          if (k.startswith("measure_") or k.startswith("count_"))
                          and k in registered],
        "新增测量工具（训练后注册）": [k for k in catalog if k not in registered],
    }
    desc_parts = []
    for group, names in groups.items():
        desc_parts.append(f"[{group}]")
        for k in names:
            desc_parts.append(f"- {k}: {catalog[k]['description']}")
    desc = "\n".join(desc_parts)
    goal = task.get("goal") or {
        "single": "验证生成模型是否为单一有效封闭实体",
        "multi": "同时验证实体有效性以及关键特征（榫槽数量或盘体尺寸）",
        "anomaly": "测量盘体关键尺寸以发现异常",
        "new": "使用训练后新增的专用测量工具完成测量",
    }.get(task["category"], "完成对应工程验证")
    prompt = (
        f"为任务 {task['tool_task_id']} 写一段可独立运行的 Python 检查代码。\n"
        f"数据目录：{base_dir}\n"
        f"模型特征：{summary}\n"
        f"任务目标：{goal}\n"
        f"可用工具目录：\n{desc}\n"
        "要求：\n"
        "1. 输出 JSON：{\"code\":\"...\",\"capabilities\":[\"工具名\",...]}；\n"
        "2. capabilities 必须列出你的代码实际实现的检查/测量能力，"
        "从可用工具目录中选择 1 个或多个，且必须与代码行为一致；\n"
        "3. 用 cadquery 读取数据目录下的 output.step；\n"
        "4. 实体有效性判定：导入 STEP 后 solids 数量恰好为 1 且总体积 > 0 即视为有效；"
        "不要因封闭性或面数检查失败而误判；\n"
        "5. 程序最后只打印 JSON {\"ok\": true/false}，不要输出其他内容；\n"
        "6. 代码必须语法正确、可独立运行，不得依赖未定义变量；\n"
        "7. 代码应轻量快速，只执行任务所需的检查/测量，避免长时间循环或多余计算。"
    )
    try:
        result = client.call_strict_tool(
            messages=[{"role": "user", "content": prompt}],
            tool_name="emit_python", tool_description="输出 Python 代码",
            tool_schema={"type": "object", "properties": {
                "code": {"type": "string"},
                "capabilities": {"type": "array", "items": {"type": "string"}},
            }, "required": ["code", "capabilities"]},
            config=llm,
        )
        args = result.arguments
        code = args.get("code", "")
        capabilities = args.get("capabilities") or []
        proc = _run_python_utf8(code, timeout=60.0)
        ok = proc.returncode == 0
        stdout = proc.stdout or ""
        stderr = (proc.stderr or "")[:200]
        inferred = _infer_capabilities_from_code(code)
        return {"tool_task_id": task["tool_task_id"], "category": task["category"],
                "selected": set(inferred),
                "ordered_selected": inferred,
                "declared_capabilities": list(capabilities),
                "expected": set(task["tool_sequence"]),
                "binding_ok": ok, "multi_complete": ok,
                "result_ok": ok and "true" in stdout.lower(),
                "new_tool_called": any(
                    c in set(task["tool_sequence"])
                    and c not in load_mcp_tool_registry()
                    and ok
                    for c in inferred),
                "stdout": stdout[:200], "stderr": stderr}
    except Exception as exc:  # noqa: BLE001
        return {"tool_task_id": task["tool_task_id"], "category": task["category"],
                "selected": set(), "ordered_selected": [],
                "expected": set(task["tool_sequence"]),
                "binding_ok": False, "multi_complete": False, "result_ok": False,
                "new_tool_called": False, "error": str(exc)[:200]}


def run_suite(tasks: list[TaskSpec], tool_tasks: list[dict[str, Any]],
              config: ExperimentConfig, *, seeds: int = 5) -> list[dict[str, Any]]:
    task_map = {t.task_id: t for t in tasks}
    client = OpenAICompatToolClient()
    results: list[dict[str, Any]] = []
    for tool_task in tool_tasks:
        task = task_map.get(tool_task["task_id"])
        if task is None:
            continue
        base_dir = str(ensure_golden(task, config))
        for interface in ("fixed", "mcp_agent", "llm_code"):
            for seed in range(seeds):
                llm = config.llm.model_copy(update={"seed": seed})
                try:
                    if interface == "fixed":
                        rec = _run_fixed(tool_task, base_dir)
                    elif interface == "mcp_agent":
                        rec = _run_mcp_agent(tool_task, base_dir, client, llm)
                    else:
                        rec = _run_llm_code(tool_task, base_dir, client, llm)
                except Exception as exc:  # noqa: BLE001
                    rec = {"tool_task_id": tool_task["tool_task_id"],
                           "category": tool_task["category"], "selected": set(),
                           "expected": set(tool_task["tool_sequence"]),
                           "binding_ok": False, "multi_complete": False,
                           "result_ok": False, "new_tool_called": False,
                           "error": str(exc)[:200]}
                rec["interface"] = interface
                rec["seed"] = seed
                results.append(stamp_record(rec, "tool", "tool_v1"))
    return results


def _precision_recall_f1(results: list[dict[str, Any]]) -> dict[str, float]:
    precisions: list[float] = []
    recalls: list[float] = []
    for r in results:
        sel = set(r.get("selected") or [])
        exp = set(r.get("expected") or [])
        if not sel and not exp:
            continue
        inter = len(sel & exp)
        precisions.append(inter / len(sel) if sel else 0.0)
        recalls.append(inter / len(exp) if exp else 0.0)
    precision = sum(precisions) / len(precisions) if precisions else 0.0
    recall = sum(recalls) / len(recalls) if recalls else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"f1": round(f1, 4), "precision": round(precision, 4), "recall": round(recall, 4)}


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for interface in ("fixed", "mcp_agent", "llm_code"):
        items = [r for r in results if r["interface"] == interface]
        prf = _precision_recall_f1(items)
        rows.append({
            "interface": interface, "runs": len(items),
            "tool_selection_f1": prf["f1"],
            "param_binding_accuracy": round(
                sum(1 for r in items if r.get("binding_ok")) / max(1, len(items)), 4),
            "multi_tool_completion": round(
                sum(1 for r in items if r.get("multi_complete")) / max(1, len(items)), 4),
            "result_accuracy": round(
                sum(1 for r in items if r.get("result_ok")) / max(1, len(items)), 4),
            "new_tool_call_rate": round(
                sum(1 for r in items if r.get("category") == "new"
                    and r.get("new_tool_called"))
                / max(1, sum(1 for r in items if r.get("category") == "new")), 4),
        })
    return {"rows": rows}
