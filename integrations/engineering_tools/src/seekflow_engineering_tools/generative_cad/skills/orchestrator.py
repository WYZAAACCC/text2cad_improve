"""Skills orchestrator — Level-1 routing + Level-2 authoring prompt builders."""

from __future__ import annotations

import json

from seekflow_engineering_tools.generative_cad.dialects.registry import export_dialect_catalog
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry as _default_dialect_registry
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
    primitive_catalog: dict | None = None,
) -> dict:
    """Build a Level-1 routing prompt for dialect selection.

    Includes both dialect catalog and primitive catalog so the LLM
    can make informed routing decisions (deterministic_primitive vs
    generative_cad_ir vs unsupported).
    """
    if dialect_catalog is None:
        dialect_catalog = export_dialect_catalog()

    if primitive_catalog is None:
        try:
            from seekflow_engineering_tools.geometry_primitives.registry import (
                list_primitive_names,
                get_primitive,
            )
            primitive_catalog = {}
            for name in list_primitive_names():
                p = get_primitive(name)
                if p is not None:
                    primitive_catalog[name] = {
                        "category": p.category,
                        "description": p.description,
                        "parameters": [
                            {"name": param.name, "type": param.type, "required": param.required}
                            for param in p.parameters
                        ],
                    }
        except Exception:
            primitive_catalog = {}

    domain_skills = {}
    for sid in (domain_skill_ids or list_domain_skills()):
        try:
            domain_skills[sid] = load_domain_skill(sid)[:2000]
        except FileNotFoundError:
            pass

    # Build user message with all context
    user_message = user_request
    if primitive_catalog:
        user_message += "\n\n--- Available Deterministic Primitives ---\n"
        user_message += "The following engineering primitives are available for deterministic, "
        user_message += "high-precision CAD generation. If the user request exactly matches "
        user_message += "a primitive's parameters, prefer route_decision='deterministic_primitive'.\n\n"
        user_message += json.dumps(primitive_catalog, indent=2, ensure_ascii=False)
    if dialect_catalog:
        user_message += "\n\n--- Available Generative CAD Dialects ---\n"
        user_message += "The following generative dialects are available for reference-geometry "
        user_message += "CAD generation. Use these when no deterministic primitive matches "
        user_message += "or the user needs flexible reference geometry.\n\n"
        user_message += json.dumps(dialect_catalog, indent=2, ensure_ascii=False)

    return {
        "system": LEVEL1_ROUTING_SYSTEM_PROMPT,
        "user": user_message,
        "output_schema": DialectSelectionPlan.model_json_schema(),
        "catalog": dialect_catalog,
        "domain_skills": domain_skills,
        "primitive_catalog": primitive_catalog,
    }


def build_level2_authoring_prompt(
    user_request: str,
    selection_plan: DialectSelectionPlan | dict,
    contracts: dict[str, dict] | None = None,
    usage_skills: dict[str, str] | None = None,
    *,
    strict_usage_skill: bool = True,
) -> dict:
    """Build a Level-2 authoring prompt for RawGcadDocument generation.

    When *usage_skills* is None (the default), Level-2 usage skills are
    automatically loaded from registered BasePackages. This ensures the
    LLM always has accurate, contract-synchronized operation guidance.

    Args:
        user_request: The original user request text.
        selection_plan: The Level-1 DialectSelectionPlan.
        contracts: Optional pre-loaded contracts dict. Auto-loaded if None.
        usage_skills: Optional pre-built usage skills dict. Auto-generated
            from BasePackages if None.
        strict_usage_skill: If True (default), fail when a selected dialect
            has no registered BasePackage. Set False for developer mode.
    """
    if isinstance(selection_plan, dict):
        selection_plan = DialectSelectionPlan.model_validate(selection_plan)

    if contracts is None:
        contracts = {}
        for sd in selection_plan.selected_dialects:
            dialect = _default_dialect_registry().get(sd.dialect)
            if dialect is not None:
                contracts[sd.dialect] = dialect.contract()

    anti_examples: dict[str, list[dict]] = {}
    if usage_skills is None:
        usage_skills = {}
        from seekflow_engineering_tools.generative_cad.base_packages.registry import (
            default_base_package_registry,
        )
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
            default_registry,
        )
        bp_reg = default_base_package_registry()
        d_reg = default_registry()
        for sd in selection_plan.selected_dialects:
            pkg = bp_reg.get(sd.dialect)
            dialect = d_reg.get(sd.dialect)
            if pkg is not None and dialect is not None:
                usage_skills[sd.dialect] = pkg.level2_usage_markdown
                anti_examples[sd.dialect] = list(pkg.anti_examples) if pkg.anti_examples else []
            elif dialect is not None:
                # Dialect exists but has no BasePackage (e.g. loft_sweep, shell_housing).
                # Generate a minimal usage skill from the dialect's contract + op specs.
                # This allows L2 authoring for all registered dialects, even those
                # without a dedicated BasePackage.
                if strict_usage_skill:
                    usage_skills[sd.dialect] = _build_minimal_usage_skill(dialect)
            elif strict_usage_skill:
                raise ValueError(
                    f"Selected dialect {sd.dialect!r} has no registered "
                    f"BasePackage. In strict mode, every selected dialect "
                    f"must have a BasePackage. Available: {bp_reg.list_ids()}"
                )

    return {
        "system": LEVEL2_AUTHORING_SYSTEM_PROMPT,
        "user": user_request,
        "output_schema": RawGcadDocument.model_json_schema(),
        "selected_dialects": [sd.model_dump() for sd in selection_plan.selected_dialects],
        "contracts": contracts,
        "usage_skills": usage_skills or {},
        "anti_examples": anti_examples,
    }


def _build_minimal_usage_skill(dialect) -> str:
    """Build a minimal Level-2 usage markdown from a dialect's contract + op specs.

    Used when a dialect has no registered BasePackage (e.g. loft_sweep, shell_housing).
    Generates LLM-friendly operation documentation from the dialect's own metadata.
    """
    lines = [
        f"# {dialect.dialect_id} v{dialect.version} — Usage Guide",
        "",
        f"Phase order: {' → '.join(dialect.phase_order)}",
        "",
        "## Available Operations",
        "",
    ]
    for (op_name, _), spec in dialect.op_specs().items():
        ps = spec.params_model.model_json_schema()
        props = ps.get("properties", {})
        required = ps.get("required", [])
        param_strs = []
        for pname, pinfo in props.items():
            req_mark = "*" if pname in required else ""
            ptype = pinfo.get("type", "?")
            desc = pinfo.get("description", "")
            ref = pinfo.get("$ref", "")
            if ref:
                ref_name = ref.split("/")[-1]
                nested = ps.get("$defs", {}).get(ref_name, {})
                nested_props = nested.get("properties", {})
                fields = ", ".join(
                    f"{k}:{v.get('type','?')}" for k, v in nested_props.items()
                )
                param_strs.append(f"{pname}{req_mark}=[{fields}]")
            elif "enum" in pinfo:
                param_strs.append(f"{pname}{req_mark}=one of {pinfo['enum']}")
            else:
                param_strs.append(f"{pname}{req_mark}:{ptype}" + (f" ({desc})" if desc else ""))
        lines.append(
            f"### {op_name} (phase={spec.phase})"
        )
        lines.append(f"Inputs: {list(spec.input_types)} → Outputs: {list(spec.output_types)}")
        lines.append(f"Params: {' | '.join(param_strs[:10])}")
        if spec.summary:
            lines.append(f"Description: {spec.summary}")
        if spec.common_mistakes:
            lines.append(f"Common mistakes: {'; '.join(spec.common_mistakes[:3])}")
        lines.append("")
    return "\n".join(lines)


def build_repair_prompt_v2(
    raw_document: dict,
    validation_report: dict,
    repair_state: dict,
    *,
    extra_diagnostics: dict | None = None,
) -> dict:
    """Build a repair prompt for iterative patch generation.

    v6.3: extra_diagnostics may contain 'compiler_middle_end',
    'planning_report', and 'geometry_health_summary' sections
    produced by the compiler middle-end. These are passed to the LLM
    alongside validation issues for more informed repair decisions.
    """
    from seekflow_engineering_tools.generative_cad.repair.patch import RepairPatchV2

    user_parts = [
        f"RawGcadDocument: {raw_document}",
        f"Validation Issues: {validation_report.get('issues', [])}",
    ]

    # ── v6.3: Include compiler diagnostics in repair prompt ──
    if extra_diagnostics:
        compiler = extra_diagnostics.get("compiler_middle_end")
        if compiler and compiler.get("diagnostics"):
            user_parts.append(
                f"Compiler Diagnostics (semantic + feasibility analysis): "
                f"{compiler['diagnostics']}"
            )
        planning = extra_diagnostics.get("planning_report")
        if planning and planning.get("issues"):
            user_parts.append(
                f"Planning Warnings (optimization opportunities): "
                f"{planning['issues']}"
            )
        health = extra_diagnostics.get("geometry_health_summary")
        if health:
            user_parts.append(
                f"Geometry Health Summary: {health}"
            )

    user_parts.append(f"Repair State: {repair_state}")

    return {
        "system": REPAIR_PATCH_SYSTEM_PROMPT_V2,
        "user": "\n\n".join(user_parts),
        "output_schema": RepairPatchV2.model_json_schema(),
    }


# ── Function calling tool builders (enum-constrained schemas) ──

def build_level1_tool() -> dict:
    """Build an OpenAI function calling tool for Level-1 routing.

    The tool schema has enum constraints on dialect names and versions,
    preventing the LLM from hallucinating invalid dialect names.

    Returns a dict suitable for the `tools` parameter of the OpenAI API.
    """
    import copy
    from seekflow_engineering_tools.generative_cad.dialects.registry import list_dialects
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

    valid_dialects = sorted(list_dialects())
    dialect_versions: dict[str, str] = {}
    reg = default_registry()
    for dn in valid_dialects:
        d = reg.get(dn)
        if d is not None:
            dialect_versions[dn] = d.version

    # v6.3: Dynamic version enum from registry, not hardcoded "0.2.0"
    all_versions = sorted(set(dialect_versions.values()))

    schema = copy.deepcopy(DialectSelectionPlan.model_json_schema())
    for _def_name, def_schema in schema.get("$defs", {}).items():
        props = def_schema.get("properties", {})
        if "dialect" in props and "version" in props:
            props["dialect"]["enum"] = valid_dialects
            if "reason" in props:
                # DialectSelectionItem: use actual registry versions
                props["version"]["enum"] = all_versions

    return {
        "type": "function",
        "function": {
            "name": "select_dialect_plan",
            "description": (
                "Select the best CAD modelling route (deterministic_primitive, "
                "generative_cad_ir, or unsupported) and choose appropriate dialects "
                "from the available set: " + ", ".join(valid_dialects) + "."
            ),
            "parameters": schema,
        },
    }


def build_level2_tool(contracts: dict[str, dict] | None = None) -> dict:
    """Build an OpenAI function calling tool for Level-2 authoring.

    Generates per-operation sub-schemas for the ``nodes`` array. Each operation
    gets a dedicated schema variant with:
    - fixed ``dialect`` (const)
    - fixed ``op`` (const)
    - fixed ``phase`` (const)
    - exact ``inputs`` count (minItems/maxItems)
    - exact ``outputs`` items (prefixItems with fixed name/type)
    - the operation's ``params`` model as the params schema

    This prevents the LLM from hallucinating field names, missing required
    outputs, or using wrong parameter structures.
    """
    import copy
    from seekflow_engineering_tools.generative_cad.dialects.registry import list_dialects
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

    valid_dialects = sorted(list_dialects())
    reg = default_registry()

    schema = copy.deepcopy(RawGcadDocument.model_json_schema())
    defs = schema.get("$defs", {})

    # ── Constrain top-level fixed-value fields ──
    top_props = schema.get("properties", {})
    if "schema_version" in top_props:
        top_props["schema_version"]["const"] = "g_cad_core_v0.2"
    if "units" in top_props:
        top_props["units"]["const"] = "mm"
    if "trust_level" in top_props:
        top_props["trust_level"]["enum"] = ["reference_geometry", "concept_geometry"]

    # ── Constrain selected_dialects and components ──
    for def_name, def_schema in defs.items():
        props = def_schema.get("properties", {})
        if set(props.keys()) == {"dialect", "version"}:
            props["dialect"]["enum"] = valid_dialects
            props["version"]["enum"] = ["0.2.0"]
        if "owner_dialect" in props and "root_node" in props and "kind_hint" in props:
            props["owner_dialect"]["enum"] = valid_dialects + ["composition"]

    # ── Build per-operation node schemas with rich descriptions ──

    # Operation-level descriptions explaining what each op does geometrically.
    # Used as description override for LLM-facing tool schemas.
    # When an op is NOT in this dict, the compiler falls back to OperationSpec.summary.
    OP_DESCRIPTIONS: dict[str, str] = {
        "revolve_profile": (
            "绕Z轴旋转2D截面轮廓生成旋转体。profile_stations定义轮廓形状。"
            "r_mm=RADIUS(半径=直径的一半)。例如外径80mm的圆盘，第一个station的r_mm=40。"
            "z_front_mm和z_rear_mm必须满足z_rear_mm > z_front_mm，差值=该段的厚度。"
            "示例 - 外径80mm内径30mm厚12mm的垫圈："
            "[{r_mm:40,z_front_mm:0,z_rear_mm:2}, {r_mm:40,z_front_mm:2,z_rear_mm:12}, {r_mm:15,z_front_mm:12,z_rear_mm:13}]"
        ),
        "cut_center_bore": (
            "切除中心通孔。diameter_mm=孔径(mm)。必须在revolve_profile之后执行。"
            "孔径必须小于旋转体的最小内径。"
        ),
        "cut_annular_groove": (
            "在面上切环形槽。inner_dia_mm/outer_dia_mm定义槽的内外直径。"
            "side='front'在前表面切，side='rear'在后表面切。depth_mm=槽深。"
            "inner_dia_mm必须小于outer_dia_mm，outer_dia_mm必须小于轮廓最大半径。"
        ),
        "cut_circular_hole_pattern": (
            "在节圆上均布通孔。count=孔数，pcd_mm=节圆直径，hole_dia_mm=孔径。"
            "pcd_mm必须小于轮廓外径且大于中心孔直径。"
        ),
        "extrude_rectangle": (
            "拉伸矩形截面生成长方体。width_mm=X方向宽度，height_mm=Y方向高度，depth_mm=Z方向拉伸深度。"
        ),
        "cut_hole": (
            "在指定位置打通孔。diameter_mm=孔径。position_mm=[x,y]为孔中心位置。"
        ),
        "cut_rectangular_pocket": (
            "切矩形凹槽。width_mm/height_mm=槽尺寸，depth_mm=槽深(必须小于底板厚度)。"
        ),
        "cut_hole_pattern_linear": (
            "矩形阵列通孔。hole_dia_mm=孔径，count_x/count_y=行列数，spacing_x_mm/spacing_y_mm=间距。"
        ),
        # v6.3: V2 hole ops — face-relative, deterministic placement
        "cut_hole_v2": (
            "在指定面上打孔(V2语义)。diameter_mm=孔径。placement包含target_face(目标面top/bottom/front/back/left/right/cylindrical)、"
            "center_uv_mm(面上UV坐标)、normal_axis(法向)、through_mode(through_all/blind)。"
            "比旧版cut_hole更精确，推荐新零件使用此操作。"
        ),
        "drill_hole_3d": (
            "在任意3D方向钻孔。diameter_mm=孔径。origin_mm=3D起点，direction=方向向量。"
            "用于斜孔、油道、冷却通道等不能用面法向表达的孔。"
        ),
        "cut_hole_pattern_linear_v2": (
            "在指定面上做矩形孔阵列(V2语义)。hole_dia_mm=孔径，count_u/count_v=行列数，"
            "spacing_u_mm/spacing_v_mm=UV方向间距。placement定义目标面和基准。"
            "比旧版更强：支持任意面的UV网格。"
        ),
        "add_rectangular_boss": (
            "在表面添加矩形凸台。width_mm/height_mm/depth_mm=凸台尺寸。position_mm=[x,y]=位置。"
        ),
        "add_rib": (
            "添加三角形加强筋。thickness_mm=筋厚，height_mm=筋高，length_mm=筋长。position_mm=[x,y]=位置。"
        ),
        "apply_safe_fillet": (
            "对边做圆角。radius_mm=圆角半径。仅在sketch_extrude中可用。"
        ),
        "apply_safe_chamfer": (
            "对边做倒角。distance_mm=倒角距离。"
        ),
        "boolean_union": (
            "合并两个实体为一个。需要恰好2个input，各来自不同组件。只在__assembly__组件中使用。"
        ),
        "boolean_cut": (
            "用一个实体切割另一个。需要恰好2个input。只在__assembly__组件中使用。"
        ),
        "translate_solid": (
            "将实体沿向量平移。vector_mm=[x,y,z]为平移向量。用于调整组件位置后做boolean操作。"
        ),
        "cut_rim_slot_pattern": (
            "在边缘切槽。count>=2为槽数，slot_depth_mm=槽深(径向)。"
        ),
        "place_component": (
            "放置组件到指定位置。position_mm=[x,y,z]。用于多组件装配。"
        ),
        "rotate_solid": (
            "旋转实体。axis_dir=[x,y,z]旋转轴方向，angle_deg=旋转角度(度)。"
        ),
    }

    # ── v6.3: Delegate op variant construction to the schema compiler ──
    # The compiler reads OperationSpec metadata (summary, usage_notes,
    # params_model field descriptions) to generate structurally correct
    # per-op schemas. We then inject Chinese descriptions as overrides.
    from seekflow_engineering_tools.generative_cad.skills.tool_schema_compiler import (
        _build_op_variants,
        _wire_node_variants,
        _constrain_top_level,
        _constrain_selected_dialects,
    )

    # Use compiler's top-level constraints (dynamic version enum)
    _constrain_top_level(schema)
    _constrain_selected_dialects(defs, valid_dialects, reg)

    # Build op variants via compiler (structurally correct, from OperationSpec)
    op_variants = _build_op_variants(valid_dialects, reg, None, defs)

    # ── Inject Chinese descriptions from OP_DESCRIPTIONS ──
    for variant in op_variants:
        title = variant.get("title", "")
        # Extract op_name from title like "axisymmetric.revolve_profile"
        if "." in title:
            op_name = title.split(".", 1)[1]
            if op_name in OP_DESCRIPTIONS:
                variant["description"] = OP_DESCRIPTIONS[op_name]

    # ── Inject field-level Chinese descriptions for critical params ──
    for _ref_name, params_schema in defs.items():
        ps_props = params_schema.get("properties", {})
        # profile_stations: the #1 LLM confusion point
        if "profile_stations" in ps_props:
            ps_props["profile_stations"]["description"] = (
                "定义旋转体的2D截面轮廓。每个station描述一段圆柱：r_mm=该段半径(直径的一半！)，"
                "z_front_mm=该段起始Z位置，z_rear_mm=该段结束Z位置。"
                "关键规则：1) z_rear_mm必须>z_front_mm; 2) 相邻station的r_mm必须不同才能形成台阶; "
                "3) 第一个station的z_front_mm是最底部，最后一个station的z_rear_mm是最顶部; "
                "4) r_mm=RADIUS(半径)，不是直径。外径=2×r_mm。"
                "示例-外径80内径30厚12垫圈:[{r:40,zf:0,zr:2},{r:40,zf:2,zr:12},{r:15,zf:12,zr:13}]"
                "示例-外径120厚16法兰:[{r:60,zf:0,zr:3},{r:60,zf:3,zr:16},{r:20,zf:16,zr:17}]"
            )
            items_schema = ps_props["profile_stations"].get("items", {})
            if isinstance(items_schema, dict):
                item_props = items_schema.get("properties", {})
                if "r_mm" in item_props:
                    item_props["r_mm"]["description"] = "该station处的半径(mm)=直径/2。例如外径80mm则r_mm=40。"
                if "z_front_mm" in item_props:
                    item_props["z_front_mm"]["description"] = "该station段的起始Z坐标(mm), 必须<z_rear_mm"
                if "z_rear_mm" in item_props:
                    item_props["z_rear_mm"]["description"] = "该station段的结束Z坐标(mm), 必须>z_front_mm"

        # Dimension fields with Chinese units
        for fname in ["diameter_mm", "hole_dia_mm"]:
            if fname in ps_props:
                ps_props[fname]["description"] = "直径(mm)。必须是正数且小于轮廓的外径。"
        for fname in ["width_mm", "height_mm", "depth_mm", "thickness_mm", "length_mm"]:
            if fname in ps_props:
                ps_props[fname]["description"] = "尺寸(mm)。必须是正数。"
        for fname in ["distance_mm", "radius_mm"]:
            if fname in ps_props:
                ps_props[fname]["description"] = "尺寸(mm)。必须是正数，且不超出零件边界。"

        # ── v6.3: DimExpr support note ──
        # Add DimExpr hint to the first numeric field in each params model
        numeric_keys = ["diameter_mm", "width_mm", "pcd_mm", "hole_dia_mm",
                        "inner_dia_mm", "outer_dia_mm", "depth_mm", "slot_depth_mm",
                        "distance_mm", "radius_mm", "thickness_mm", "length_mm",
                        "height_mm", "spacing_x_mm", "spacing_y_mm",
                        "spacing_u_mm", "spacing_v_mm"]
        for nk in numeric_keys:
            if nk in ps_props and "DimExpr" not in str(ps_props[nk].get("description", "")):
                current = ps_props[nk].get("description", "尺寸(mm)")
                ps_props[nk]["description"] = (
                    f"{current} 也可用DimExpr表达式代替具体数值，如: "
                    r'{"kind":"dim_expr","op":"ref","args":[{"root_kind":"node","root_id":"n1","path":["radius_max_mm"]}]}'
                )
        for fname in ["count", "count_x", "count_y", "count_u", "count_v"]:
            if fname in ps_props:
                ps_props[fname]["description"] = "数量。必须是>=1的整数。"
        if "position_mm" in ps_props:
            ps_props["position_mm"]["description"] = "位置坐标[x,y]或[x,y,z](mm)。相对于零件中心的偏移。"
        if "side" in ps_props:
            ps_props["side"]["description"] = "操作面: 'front'=前表面(Z最大处), 'rear'=后表面(Z最小处)"

    # ── v6.3: Use compiler's wiring for multi-component guidance ──
    _wire_node_variants(schema, op_variants)

    # Override with Chinese descriptions for DeepSeek
    comp_prop = schema.get("properties", {}).get("components", {})
    if comp_prop:
        comp_prop["description"] = (
            "组件列表。对于单零件(如垫圈、法兰、轴、板)，只需1个组件。"
            "对于多零件装配(如支架+底板、铰链两片、夹钳)，需要每个独立零件1个组件+1个__assembly__组件。"
            "__assembly__组件的owner_dialect必须是'composition'。"
            "非assembly组件只能包含其owner_dialect对应的节点。"
        )

    nodes_prop = schema.get("properties", {}).get("nodes", {})
    if nodes_prop:
        nodes_prop["description"] = (
            "操作节点列表。每个节点选择下面anyOf中的一个操作schema。"
            "单零件时所有节点属于同一个组件。多零件装配时："
            "1) 先为每个独立零件创建节点(属于各自的组件); "
            "2) 再在__assembly__组件中创建composition节点(boolean_union等)来合并它们。"
            "composition节点通过inputs引用其他组件的最终节点来实现跨组件合并。"
        )

    return {
        "type": "function",
        "function": {
            "name": "generate_raw_gcad_document",
            "description": (
                "Generate a RawGcadDocument JSON for the G-CAD Core IR. "
                "Each node in the 'nodes' array must match one of the allowed "
                "operation schemas exactly. Available dialects: "
                + ", ".join(valid_dialects) + "."
            ),
            "parameters": schema,
        },
    }


def get_level1_tool_choice() -> dict:
    """Return tool_choice dict that forces the LLM to call the L1 tool."""
    return {"type": "function", "function": {"name": "select_dialect_plan"}}


def get_level2_tool_choice() -> dict:
    """Return tool_choice dict that forces the LLM to call the L2 tool."""
    return {"type": "function", "function": {"name": "generate_raw_gcad_document"}}
