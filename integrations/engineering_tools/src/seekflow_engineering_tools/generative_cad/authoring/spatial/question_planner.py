"""Clarification question planner with priority-based budgeting.

Priority formula: priority = impact * uncertainty / max(answer_cost, 0.1)
Only high-priority unknowns are converted to questions.

Architecture:
- plan_questions() first tries LLM refinement (question_caller) to generate
  context-specific options tailored to each question.
- Falls back to deterministic template-based options (in Chinese) when
  no LLM caller is available.
"""
from __future__ import annotations
from typing import Any

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft,
    SpatialUnknown,
    SpatialQuestion,
    SpatialQuestionOption,
)

DEFAULT_QUESTION_BUDGET = 3
MIN_PRIORITY_THRESHOLD = 0.05  # Allow moderate-impact unknowns through


def plan_questions(
    object_graph: MechanicalObjectGraphDraft,
    budget: int = DEFAULT_QUESTION_BUDGET,
    min_priority: float = MIN_PRIORITY_THRESHOLD,
    question_caller: Any | None = None,
    llm_config: Any | None = None,
) -> list[SpatialQuestion]:
    if not object_graph.unknowns:
        return []
    import sys
    print(f"[PLAN] {len(object_graph.unknowns)} unknowns, caller={'yes' if question_caller else 'no'}", file=sys.stderr, flush=True)
    scored: list[tuple[float, SpatialUnknown]] = []
    for unk in object_graph.unknowns:
        priority = _compute_priority(unk)
        if priority >= min_priority:
            scored.append((priority, unk))
    scored.sort(key=lambda x: x[0], reverse=True)
    questions: list[SpatialQuestion] = []
    for priority, unk in scored[:budget]:
        q = _unknown_to_question(unk, priority)
        questions.append(q)
    # LLM refinement disabled — the object graph extraction LLM now generates
    # concrete suggested_option_labels/descriptions directly, which are used
    # as question options in _unknown_to_question(). This is more reliable
    # than a separate refinement call (which fails with JSON parse errors).
    return questions


def _compute_priority(unk: SpatialUnknown) -> float:
    impact = max(0.0, min(1.0, unk.impact))
    uncertainty = max(0.0, min(1.0, unk.uncertainty))
    answer_cost = max(0.1, unk.answer_cost)
    raw = (impact * uncertainty) / answer_cost
    return max(0.0, min(1.0, raw))


def _unknown_to_question(unk: SpatialUnknown, priority: float) -> SpatialQuestion:
    # Prefer LLM-generated concrete options; fall back to templates
    if unk.suggested_option_labels and len(unk.suggested_option_labels) >= 2:
        options: list[SpatialQuestionOption] = []
        for idx in range(min(len(unk.suggested_option_labels), 4)):
            label = unk.suggested_option_labels[idx]
            desc = (
                unk.suggested_option_descriptions[idx]
                if idx < len(unk.suggested_option_descriptions)
                else ""
            )
            options.append(SpatialQuestionOption(
                option_id=chr(ord("A") + idx),
                label=label,
                description=desc,
                recommended=(idx == 0),
                geometric_consequence=label,
            ))
    else:
        options = _default_options_for_kind(unk)

    return SpatialQuestion(
        question_id=f"q_{unk.unknown_id}",
        unknown_id=unk.unknown_id,
        type=unk.kind,
        entities=list(unk.entities),
        question_text=unk.question_hint or f"{', '.join(unk.entities)} 应如何布置？",
        why_it_matters=unk.reason or f"{', '.join(unk.entities)} 的布置不当可能导致装配错误",
        impact=unk.impact,
        uncertainty=unk.uncertainty,
        answer_cost=unk.answer_cost,
        priority=round(priority, 3),
        options=options,
        allow_custom=True,
        allow_auto=True,
    )


def _default_options_for_kind(unk: SpatialUnknown) -> list[SpatialQuestionOption]:
    """根据 unknown 类型返回中文选项模板。

    每种选项的描述都包含具体的工程上下文，帮助用户理解
    '推荐'或'标准'到底意味着什么。
    """
    kind = unk.kind

    if kind == "component_count":
        entities_str = "、".join(unk.entities) if unk.entities else "组件"
        return [
            SpatialQuestionOption(
                option_id="A",
                label="按描述数量（推荐）",
                description=f"「{entities_str}」的数量与提示描述完全一致。当你对具体数量有明确要求时，这是最安全的选择。",
                recommended=True,
                geometric_consequence=f"「{entities_str}」数量与提示一致",
            ),
            SpatialQuestionOption(
                option_id="B",
                label="指定其他数量",
                description=f"指定「{entities_str}」的不同数量，以满足载荷分布、冗余设计或成本优化等需求。",
                geometric_consequence=f"「{entities_str}」数量将改变装配布局",
            ),
        ]

    if kind == "numeric_value":
        entities_str = "、".join(unk.entities) if unk.entities else "该参数"
        reason_short = unk.reason[:60] if unk.reason else ""
        return [
            SpatialQuestionOption(
                option_id="A",
                label=f"推荐值（根据已知尺寸自动匹配）",
                description=(
                    f"系统根据你已明确指定的尺寸，按机械设计惯例和行业标准"
                    f"（GB/T、ISO、ANSI）为「{entities_str}」自动匹配最合适的数值。"
                    f"{'原因：' + reason_short if reason_short else ''}"
                    f"具体数值记录在输出元数据中，可在下载的 metadata.json 中查看。"
                ),
                recommended=True,
                auto_policy="auto_mechanical",
                geometric_consequence=f"「{entities_str}」采用行业标准推荐值",
            ),
            SpatialQuestionOption(
                option_id="B",
                label=f"偏大一级（安全裕量更大）",
                description=(
                    f"为「{entities_str}」选取比标准推荐值偏大一级的规格。"
                    f"适用于高压、重载、高温或需要更大安全系数的场合。"
                    f"可能增加材料用量和零件重量。"
                ),
                geometric_consequence=f"「{entities_str}」取偏大一级规格",
            ),
        ]

    if kind == "material_specification":
        entities_str = "、".join(unk.entities) if unk.entities else "该零件"
        desc = (
            f"根据「{entities_str}」的机械用途，自动选择最常用的工程材料"
            f"（一般结构件→碳钢Q235/45#，耐腐蚀→304不锈钢，"
            f"管道法兰→按压力等级选碳钢或不锈钢）。"
            f"材料选择不影响几何形状，仅作为元数据记录。"
        )
        return [
            SpatialQuestionOption(
                option_id="A",
                label="标准材料（推荐）",
                description=desc,
                recommended=True,
                auto_policy="auto_mechanical",
                geometric_consequence="材料选择不影响几何形状，仅记录在元数据中",
            ),
        ]

    if kind == "relative_placement":
        entities_str = "、".join(unk.entities) if unk.entities else "组件"
        desc_a = (
            f"按照「{entities_str}」的标准机械布局放置："
            f"同轴零件中心对齐，叠放零件面面接触，"
            f"螺栓孔在螺栓圆上均匀分布。"
            f"这遵循通用工程惯例，是最安全的默认选择。"
        )
        desc_b = (
            f"「{entities_str}」关于中心平面对称放置。"
            f"适用于需要镜像布置的场景，例如两个相同的支架"
            f"分别安装在壳体两侧，或对称的螺栓孔布局。"
        )
        return [
            SpatialQuestionOption(
                option_id="A",
                label="常规布局（推荐）",
                description=desc_a,
                recommended=True,
                auto_policy="auto_mechanical",
                geometric_consequence=f"「{entities_str}」按标准机械惯例放置",
            ),
            SpatialQuestionOption(
                option_id="B",
                label="对称布局",
                description=desc_b,
                geometric_consequence=f"「{entities_str}」关于中心平面镜像放置",
            ),
        ]

    if kind == "symmetry":
        entities_str = "、".join(unk.entities) if unk.entities else "组件"
        return [
            SpatialQuestionOption(
                option_id="A",
                label="对称（推荐）",
                description=f"「{entities_str}」关于中心平面对称放置，载荷均衡、应力均匀。",
                recommended=True,
                geometric_consequence=f"「{entities_str}」在YZ平面上互为镜像",
            ),
            SpatialQuestionOption(
                option_id="B",
                label="非对称 / 独立放置",
                description=f"「{entities_str}」各自独立放置，适用于两侧需要不同偏移量或高度的场景。",
                geometric_consequence=f"「{entities_str}」可有不同的X坐标",
            ),
        ]

    if kind == "assembly_vs_fused":
        entities_str = "、".join(unk.entities) if unk.entities else "组件"
        return [
            SpatialQuestionOption(
                option_id="A",
                label="分离装配（推荐）",
                description=f"「{entities_str}」保持为独立实体，通过空间约束（面接触、同轴对齐）关联。保留各零件独立标识，可出制造图纸和BOM。",
                recommended=True,
                geometric_consequence=f"「{entities_str}」将是具有空间关系的独立实体",
            ),
            SpatialQuestionOption(
                option_id="B",
                label="融合为单体",
                description=f"「{entities_str}」通过布尔并集合并为单个实体。仅适用于概念参考，不可用于制造！",
                geometric_consequence=f"「{entities_str}」合并为单个实体",
            ),
        ]

    if kind == "spacing":
        entities_str = "、".join(unk.entities) if unk.entities else "组件"
        return [
            SpatialQuestionOption(
                option_id="A",
                label="默认间距（推荐）",
                description=f"「{entities_str}」采用机械上合适的间隙：螺栓用标准间隙孔，叠放为零间隙，旋转件按轴径选运转间隙。",
                recommended=True,
                auto_policy="auto_mechanical",
                geometric_consequence=f"「{entities_str}」具有标准机械间隙",
            ),
            SpatialQuestionOption(
                option_id="B",
                label="紧密配合",
                description=f"「{entities_str}」采用最小间隙或零间隙，适用于过盈配合、压配合等紧凑装配场景。",
                geometric_consequence=f"「{entities_str}」以接近零间隙放置",
            ),
        ]

    if kind == "axis_direction":
        entities_str = "、".join(unk.entities) if unk.entities else "该组件"
        return [
            SpatialQuestionOption(
                option_id="A",
                label="标准方向（推荐）",
                description=f"「{entities_str}」采用默认轴向：轴沿Z（竖直）或X（水平），孔沿Z自上而下。遵循加工和装配惯例。",
                recommended=True,
                auto_policy="auto_mechanical",
                geometric_consequence=f"「{entities_str}」轴向采用机械标准方向",
            ),
        ]

    # face_selection, contact_relation, feature_location, port_direction 等兜底
    entities_str = "、".join(unk.entities) if unk.entities else "该参数"
    return [
        SpatialQuestionOption(
            option_id="A",
            label="推荐默认值",
            description=f"对「{entities_str}」使用机械上最常规的选择。系统将根据工程实践选取标准值并记录在日志中。",
            recommended=True,
            auto_policy="auto_mechanical",
            geometric_consequence="采用标准机械布局",
        ),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# LLM Refinement — 要求 LLM 输出中文选项
# ═══════════════════════════════════════════════════════════════════════════════

def _refine_questions_with_llm(
    questions: list[SpatialQuestion],
    object_graph: MechanicalObjectGraphDraft,
    question_caller: Any,
    llm_config: Any,
) -> list[SpatialQuestion]:
    """调用 LLM 生成上下文特定的选项，替代通用模板选项。"""
    from seekflow_engineering_tools.generative_cad.authoring.spatial.prompts import (
        QUESTION_PLANNER_SYSTEM_PROMPT,
    )
    from seekflow_engineering_tools.generative_cad.authoring.spatial.tool_schemas import (
        build_question_planner_tool_schema,
    )

    try:
        import sys
        print(f"[REFINE] Entering refinement with {len(questions)} questions", file=sys.stderr, flush=True)
        q_summary = _build_question_context(questions, object_graph)
        result = question_caller.call_strict_tool(
            messages=[
                {"role": "system", "content": QUESTION_PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": q_summary},
            ],
            tool_name="emit_questions",
            tool_description="生成精细化的澄清问题，选项为中文",
            tool_schema=build_question_planner_tool_schema(),
            model_config=llm_config.author,
        )
        refined_data = result.arguments
        refined_questions_data = refined_data.get("questions", [])
        # DEBUG: print what the LLM actually returned
        import sys
        print(f"[REFINE] LLM returned {len(refined_questions_data)} questions", file=sys.stderr, flush=True)
        if refined_questions_data:
            print(f"[REFINE] First q keys: {list(refined_questions_data[0].keys())}", file=sys.stderr, flush=True)
            first_opts = refined_questions_data[0].get("options", [])
            print(f"[REFINE] First q options count: {len(first_opts)}", file=sys.stderr, flush=True)
            if first_opts:
                print(f"[REFINE] First opt: {first_opts[0]}", file=sys.stderr, flush=True)
        else:
            print(f"[REFINE] Raw keys: {list(refined_data.keys())}", file=sys.stderr, flush=True)
        if not refined_questions_data:
            import logging
            logging.getLogger(__name__).warning(
                "LLM refinement returned no questions. Raw keys: %s",
                list(refined_data.keys()) if refined_data else "none",
            )
            return questions

        # Build question map — first by exact question_id, then by position
        llm_qmap: dict[str, dict] = {}
        for rq in refined_questions_data:
            llm_qmap[rq.get("question_id", "")] = rq

        merged: list[SpatialQuestion] = []
        for idx, q in enumerate(questions):
            # Try exact question_id match first, then fall back to positional match
            refined = llm_qmap.get(q.question_id)
            if refined is None and idx < len(refined_questions_data):
                refined = refined_questions_data[idx]
                # Verify it has the right shape
                if not isinstance(refined, dict) or not refined.get("options"):
                    refined = None

            if refined and refined.get("options"):
                new_options: list[SpatialQuestionOption] = []
                for opt_data in refined["options"]:
                    new_options.append(SpatialQuestionOption(
                        option_id=str(opt_data.get("option_id", "?")),
                        label=str(opt_data.get("label", "")),
                        description=str(opt_data.get("description", "")),
                        recommended=bool(opt_data.get("recommended", False)),
                        geometric_consequence=str(
                            opt_data.get("geometric_consequence", "")
                        ),
                        auto_policy=opt_data.get("auto_policy"),
                    ))
                if refined.get("question_text"):
                    q.question_text = str(refined["question_text"])
                if refined.get("why_it_matters"):
                    q.why_it_matters = str(refined["why_it_matters"])
                q.options = new_options
            merged.append(q)

        return merged
    except Exception as e:
        import sys, traceback
        print(f"[REFINE] FAILED: {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return questions


def _build_question_context(
    questions: list[SpatialQuestion],
    object_graph: MechanicalObjectGraphDraft,
) -> str:
    """为 LLM 问题精炼器构建上下文摘要，要求输出中文。"""
    lines: list[str] = []
    lines.append("## 原始用户需求\n")
    lines.append(f"组件数量: {len(object_graph.components)}")
    for c in object_graph.components:
        lines.append(
            f"  - {c.component_id}: {c.role}"
            + (f" ({c.kind_hint})" if c.kind_hint else "")
        )
        # Include known dimensions directly
        if c.known_dimensions:
            for kd in c.known_dimensions:
                lines.append(f"      已知: {kd.name} = {kd.value_mm}mm")
        if c.source_text:
            lines.append(f"      来源: {c.source_text}")
    if object_graph.assumptions:
        lines.append(f"\n假设: {', '.join(object_graph.assumptions[:5])}")

    lines.append("\n## 待精炼的问题\n")
    for i, q in enumerate(questions, 1):
        lines.append(f"### 问题{i}")
        lines.append(f"  question_id: {q.question_id}  ← 输出时必须保留此ID")
        lines.append(f"  问题文本: {q.question_text}")
        lines.append(f"  类型: {q.type}")
        lines.append(f"  涉及实体: {', '.join(q.entities)}")
        lines.append(f"  为什么重要: {q.why_it_matters}")
        lines.append(f"  影响程度: {q.impact}, 不确定度: {q.uncertainty}")
        lines.append(f"  当前种子选项（必须替换为具体数值）:")
        for o in q.options:
            lines.append(f"    [{o.option_id}] {o.label}")
        lines.append("")

    # List known dimensions from the object graph to help the LLM calculate options
    known_dims = ""
    for c in object_graph.components:
        if hasattr(c, 'known_dimensions') and c.known_dimensions:
            known_dims += f"\n  已知尺寸（来自{c.component_id}）:"
            # known_dimensions might be a list of dicts or dict
            kd = c.known_dimensions
            if isinstance(kd, list):
                for item in kd:
                    if hasattr(item, 'name') and hasattr(item, 'value_mm'):
                        known_dims += f"\n    {item.name}: {item.value_mm}mm"
            elif isinstance(kd, dict):
                for k, v in kd.items():
                    known_dims += f"\n    {k}: {v}mm"

    lines.append(
        "\n## 核心要求 — 必须为每个问题生成具体数值选项\n\n"
        "你收到的每个问题目前都有一个占位式选项（如'推荐值'）。"
        "你的任务是用**具体的、可供工程师直接选择的数值选项**来替换它们。\n\n"
        "每个问题必须生成 2-4 个选项，每个选项：\n"
        "- label：具体数值或标准名 + 简短理由，如「DN100 φ114mm（推荐，匹配标准管道）」\n"
        "- description：2-3句话说明①用什么标准/惯例 ②为什么适用此尺寸 ③取舍\n"
        "- recommended：有且仅有一个标记为 true\n\n"
        "计算具体数值的方法：根据用户已给的已知尺寸，查询标准工程惯例。"
        "例如外径250mm法兰→中心通孔约DN150(168mm)，PCD≈210mm，螺栓8/12个。\n\n"
        "绝对禁止输出：\n"
        "- 抽象类别名（如「标准值」「推荐值」「常规布局」）作为唯一选项\n"
        "- 保留占位符（如「[待LLM替换]」）\n"
        f"已知尺寸参考:{known_dims}\n\n"
        "保留 question_id 不变。全部中文。只返回严格 tool arguments。"
    )
    return "\n".join(lines)
