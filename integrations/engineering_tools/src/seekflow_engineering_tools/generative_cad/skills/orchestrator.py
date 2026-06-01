"""Skills orchestrator — Level-1 routing + Level-2 authoring prompt builders."""

from __future__ import annotations

import json

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
    dialect_versions = {}
    reg = default_registry()
    for dn in valid_dialects:
        d = reg.get(dn)
        if d is not None:
            dialect_versions[dn] = d.version

    schema = copy.deepcopy(DialectSelectionPlan.model_json_schema())
    for def_name, def_schema in schema.get("$defs", {}).items():
        props = def_schema.get("properties", {})
        if "dialect" in props and "version" in props:
            props["dialect"]["enum"] = valid_dialects
            if "reason" in props:
                # DialectSelectionItem: constrain version too
                props["version"]["enum"] = ["0.2.0"]

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

    # Operation-level descriptions explaining what each op does geometrically
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

    op_variants: list[dict] = []
    for dn in valid_dialects:
        d = reg.get(dn)
        if d is None:
            continue
        for (op_name, _op_ver), spec in d.op_specs().items():
            # Build the exact outputs array
            outputs = []
            for otype in spec.output_types:
                if otype == "solid":
                    outputs.append({"name": "body", "type": "solid"})
                elif otype == "frame":
                    outputs.append({"name": "outer_frame", "type": "frame"})

            # Build per-op params schema
            params_schema = copy.deepcopy(spec.params_model.model_json_schema())
            ref_name = f"{dn}__{op_name}_params"
            params_schema["title"] = ref_name

            # ── Inject field-level Chinese descriptions ──
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
                ps_props["profile_stations"]["minItems"] = 2
                # Also describe items
                items_schema = ps_props["profile_stations"].get("items", {})
                if isinstance(items_schema, dict):
                    item_props = items_schema.get("properties", {})
                    if "r_mm" in item_props:
                        item_props["r_mm"]["description"] = "该station处的半径(mm)=直径/2。例如外径80mm则r_mm=40。相邻station的r_mm必须不同。"
                    if "z_front_mm" in item_props:
                        item_props["z_front_mm"]["description"] = "该station段的起始Z坐标(mm), 必须<z_rear_mm"
                    if "z_rear_mm" in item_props:
                        item_props["z_rear_mm"]["description"] = "该station段的结束Z坐标(mm), 必须>z_front_mm"
                    if "z_mm" in item_props:
                        item_props["z_mm"]["description"] = "该station的Z坐标(mm)"

            # diameter_mm fields
            for fname in ["diameter_mm", "hole_dia_mm"]:
                if fname in ps_props:
                    ps_props[fname]["description"] = f"直径(mm)。必须是正数且小于轮廓的外径。"

            # Dimension fields with units
            for fname in ["inner_dia_mm", "outer_dia_mm", "pcd_mm"]:
                if fname in ps_props:
                    ps_props[fname]["description"] = f"直径(mm)。"

            for fname in ["width_mm", "height_mm", "depth_mm", "thickness_mm", "length_mm"]:
                if fname in ps_props:
                    ps_props[fname]["description"] = f"尺寸(mm)。必须是正数。"

            for fname in ["distance_mm", "radius_mm", "slot_depth_mm"]:
                if fname in ps_props:
                    ps_props[fname]["description"] = f"尺寸(mm)。必须是正数，且不超出零件边界。"

            for fname in ["count", "count_x", "count_y"]:
                if fname in ps_props:
                    ps_props[fname]["description"] = f"数量。必须是>=1的整数。"

            # position_mm
            if "position_mm" in ps_props:
                ps_props["position_mm"]["description"] = "位置坐标[x,y]或[x,y,z](mm)。相对于零件中心的偏移。"

            # side field
            if "side" in ps_props:
                ps_props["side"]["description"] = "操作面: 'front'=前表面(Z最大处), 'rear'=后表面(Z最小处)"

            # vector_mm
            if "vector_mm" in ps_props:
                ps_props["vector_mm"]["description"] = "平移向量[x,y,z](mm)。正Z向上移动，负Z向下移动。"

            # axis
            if "axis" in ps_props:
                ps_props["axis"]["description"] = "旋转轴方向: 'Z'=绕Z轴"

            defs[ref_name] = params_schema

            # Build the op variant
            op_desc = OP_DESCRIPTIONS.get(op_name, f"{op_name}操作。参数见params schema。")
            variant = {
                "type": "object",
                "title": f"{dn}.{op_name}",
                "description": op_desc,
                "properties": {
                    "id": {"type": "string", "description": "节点唯一ID，如n1, n_body, n_cut"},
                    "component": {"type": "string", "description": "所属组件ID"},
                    "dialect": {"const": dn},
                    "op": {"const": op_name},
                    "op_version": {"const": "1.0.0"},
                    "phase": {"const": spec.phase},
                    "inputs": {
                        "type": "array",
                        "description": f"输入引用列表(恰好{len(spec.input_types)}个). 每个引用指向之前node的输出.",
                        "minItems": len(spec.input_types),
                        "maxItems": len(spec.input_types),
                        "items": {
                            "type": "object",
                            "properties": {
                                "node": {"type": "string", "description": "生产者node的id"},
                                "output": {"type": "string", "description": "输出名称, 通常是'body'"},
                            },
                            "required": ["node", "output"],
                            "additionalProperties": False,
                        },
                    },
                    "outputs": {
                        "type": "array",
                        "description": f"节点输出列表(恰好{len(outputs)}个)",
                        "minItems": len(outputs),
                        "maxItems": len(outputs),
                        "prefixItems": [
                            {"const": o} for o in outputs
                        ] if outputs else [],
                    } if outputs else {"type": "array", "maxItems": 0},
                    "params": {"$ref": f"#/$defs/{ref_name}"},
                    "required": {"const": True, "description": "是否必须执行"},
                    "degradation_policy": {"const": "fail", "description": "失败时的降级策略. 'fail'=直接报错."},
                },
                "required": [
                    "id", "component", "dialect", "op", "op_version",
                    "phase", "inputs", "outputs", "params",
                    "required", "degradation_policy",
                ],
                "additionalProperties": False,
            }
            op_variants.append(variant)

    # ── Add multi-component guidance to top-level schema ──
    # Guide LLM on when and how to create multiple components
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

    # ── Replace nodes.items with per-op discriminated union ──
    if nodes_prop:
        nodes_prop["items"] = {"anyOf": op_variants}

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
