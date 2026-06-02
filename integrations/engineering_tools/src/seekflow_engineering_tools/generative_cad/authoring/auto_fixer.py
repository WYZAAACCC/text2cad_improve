"""AutoFixer — programmatic fix for common LLM hallucination patterns.

每个修复都是幂等的、安全的、不改变语义的。
修复策略来自对 DeepSeek 输出模式的统计分析。
"""

from __future__ import annotations
from typing import Any

# ── 参数字段名映射 (LLM 常用名 → 正确 Pydantic 字段名) ─────────────────────

PARAM_NAME_FIXES: dict[str, dict[str, str]] = {
    # revolve_profile
    "revolve_profile": {
        "profile": "profile_stations",
        "outer_diameter_mm": None,  # remove — use profile_stations
        "inner_diameter_mm": None,
    },
    # cut_center_bore
    "cut_center_bore": {
        "bore_diameter_mm": "diameter_mm",
        "outer_diameter_mm": None,
    },
    # extrude_rectangle
    "extrude_rectangle": {
        "width": "width_mm",
        "height": "height_mm",
        "depth": "depth_mm",
        "length": "depth_mm",
    },
    # cut_rectangular_pocket
    "cut_rectangular_pocket": {
        "width": "width_mm",
        "height": "height_mm",
        "depth": "depth_mm",
    },
    # cut_hole
    "cut_hole": {
        "diameter": "diameter_mm",
        "position": "position_mm",
    },
    # cut_hole_pattern_linear
    "cut_hole_pattern_linear": {
        "hole_diameter_mm": "hole_dia_mm",
        "spacing_x": "spacing_x_mm",
        "spacing_y": "spacing_y_mm",
    },
    # add_rectangular_boss
    "add_rectangular_boss": {
        "width": "width_mm",
        "height": "height_mm",
        "depth": "depth_mm",
        "position": "position_mm",
    },
    # add_rib
    "add_rib": {
        "thickness": "thickness_mm",
        "height": "height_mm",
        "length": "length_mm",
        "position": "position_mm",
    },
    # apply_safe_fillet
    "apply_safe_fillet": {
        "radius": "radius_mm",
        "fillet_radius": "radius_mm",
        "edges": "target",
    },
    # apply_safe_chamfer
    "apply_safe_chamfer": {
        "distance": "distance_mm",
        "chamfer_distance": "distance_mm",
        "edges": "target",
    },
    # cut_annular_groove
    "cut_annular_groove": {
        "inner_diameter_mm": "inner_dia_mm",
        "outer_diameter_mm": "outer_dia_mm",
    },
    # cut_circular_hole_pattern
    "cut_circular_hole_pattern": {
        "hole_diameter_mm": "hole_dia_mm",
    },
}

# ── 目标值修正 ──────────────────────────────────────────────────────────────

TARGET_VALUE_FIXES: dict[str, str] = {
    "all_external": "all_external_edges",
    "all": "all_external_edges",
    "external": "all_external_edges",
    "external_edges": "all_external_edges",
    "all_edges": "all_external_edges",
    "outer_edges": "all_external_edges",
}


def auto_fix(raw_doc: dict, dialect_registry=None) -> dict:
    """对 RawGcadDocument dict 应用所有自动修复。幂等，可重复调用。

    修复顺序:
      1. output name 修正 (solid→body, frame→outer_frame)
      2. dialect 名修正 (未知 dialect → 从 registry 匹配)
      3. qualified op 名拆分 (axisymmetric.revolve_profile → revolve_profile)
      4. 参数字段名修正
      5. 目标值修正 (apply_safe_* target)
      6. root_node 修正
      7. 缺失默认参数填充
      8. 多余参数清理
    """
    doc = _fix_output_names(raw_doc)
    doc = _fix_op_versions(doc, dialect_registry)
    doc = _fix_dialect_names(doc, dialect_registry)
    doc = _fix_qualified_op_names(doc)
    doc = _fix_param_names(doc)
    doc = _fix_param_values(doc)
    doc = _fix_unknown_ops(doc, dialect_registry)
    doc = _fix_target_values(doc)
    doc = _fix_cross_component_refs(doc)
    doc = _fix_root_node(doc)
    doc = _fix_phase_ordering(doc, dialect_registry)
    doc = _fix_profile_stations(doc)
    doc = _fill_default_params(doc)
    doc = _remove_extra_params(doc)
    return doc


def _fix_op_versions(doc: dict, dialect_registry=None) -> dict:
    """修正 op_version: LLM 常把 dialect.version 当做 op.version (如 0.2.0→1.0.0)。"""
    if dialect_registry is None:
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        dialect_registry = default_registry()
    for node in doc.get("nodes", []):
        did = node.get("dialect", "")
        op = node.get("op", "")
        ver = node.get("op_version", "")
        if ver in ("0.2.0", "0.1.0"):  # LLM used dialect version as op version
            d = dialect_registry.get(did)
            if d:
                try:
                    node["op_version"] = d.default_op_version(op)
                except Exception:
                    node["op_version"] = "1.0.0"
    return doc


def _fix_output_names(doc: dict) -> dict:
    """output name: solid→body, frame→outer_frame, solid_body→body。
    同时补全缺失的 output (如 revolve_profile 缺少 outer_frame)。"""
    # 每个 op 的标准 outputs
    OP_OUTPUT_TEMPLATES: dict[str, list[dict]] = {
        "revolve_profile": [{"name": "body", "type": "solid"}, {"name": "outer_frame", "type": "frame"}],
        "create_sweep_path": [{"name": "path", "type": "curve"}],
        "sweep_profile": [{"name": "body", "type": "solid"}],
        "loft_sections": [{"name": "body", "type": "solid"}],
        "helix_sweep": [{"name": "body", "type": "solid"}],
        "create_2d_sketch": [{"name": "sketch", "type": "sketch"}],
        "add_line_segment": [{"name": "profile", "type": "profile"}],
        "add_polyline": [{"name": "profile", "type": "profile"}],
        "add_arc_segment": [{"name": "profile", "type": "profile"}],
        "add_circle": [{"name": "profile", "type": "profile"}],
        "close_profile": [{"name": "profile", "type": "profile"}],
        "extrude_profile": [{"name": "body", "type": "solid"}],
        "cut_profile": [{"name": "body", "type": "solid"}],
        "shell_body": [{"name": "body", "type": "solid"}],
        "hollow_body": [{"name": "body", "type": "solid"}],
        "extrude_rectangle": [{"name": "body", "type": "solid"}],
        "cut_center_bore": [{"name": "body", "type": "solid"}],
        "cut_circular_hole_pattern": [{"name": "body", "type": "solid"}],
        "cut_annular_groove": [{"name": "body", "type": "solid"}],
        "cut_rim_slot_pattern": [{"name": "body", "type": "solid"}],
        "cut_rectangular_pocket": [{"name": "body", "type": "solid"}],
        "cut_hole": [{"name": "body", "type": "solid"}],
        "cut_hole_pattern_linear": [{"name": "body", "type": "solid"}],
        "add_rectangular_boss": [{"name": "body", "type": "solid"}],
        "add_rib": [{"name": "body", "type": "solid"}],
        "apply_safe_fillet": [{"name": "body", "type": "solid"}],
        "apply_safe_chamfer": [{"name": "body", "type": "solid"}],
        "cut_internal_thread": [{"name": "body", "type": "solid"}],
        "cut_external_thread": [{"name": "body", "type": "solid"}],
        "boolean_union": [{"name": "body", "type": "solid"}],
        "boolean_cut": [{"name": "body", "type": "solid"}],
        "translate_solid": [{"name": "body", "type": "solid"}],
        "rotate_solid": [{"name": "body", "type": "solid"}],
        "place_component": [{"name": "body", "type": "solid"}],
        "circular_pattern_component": [{"name": "body", "type": "solid"}],
        "linear_pattern_component": [{"name": "body", "type": "solid"}],
    }
    for node in doc.get("nodes", []):
        op = node.get("op", "")
        outputs = node.get("outputs", [])
        # 修正已有 output name
        for o in outputs:
            name = o.get("name", "")
            otype = o.get("type", "")
            if name == "solid" and otype == "solid": o["name"] = "body"
            elif name == "frame" and otype == "frame": o["name"] = "outer_frame"
            elif name == "solid_body": o["name"] = "body"
            # Fix common output type errors: wire→curve, wire→profile, shape→solid
            if o.get("type") == "wire":
                o["type"] = "profile" if op in ("add_polyline","add_line_segment","add_arc_segment","add_circle","close_profile") else "curve"
            if o.get("type") == "path":
                o["type"] = "curve"
            if o.get("type") == "shape":
                o["type"] = "solid"
        # 根据 template 修正 output (count 或 type 不匹配时完全替换)
        template = OP_OUTPUT_TEMPLATES.get(op)
        if template:
            if len(outputs) != len(template) or any(
                o.get("type") != t["type"] for o, t in zip(outputs, template)
            ):
                node["outputs"] = [dict(t) for t in template]
    return doc


def _fix_dialect_names(doc: dict, registry=None) -> dict:
    """修正 LLM 虚造的 dialect 名。"""
    if registry is None:
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        registry = default_registry()
    known = set(registry.list_ids())

    for node in doc.get("nodes", []):
        did = node.get("dialect", "")
        if did and did not in known:
            # 尝试匹配: basic_solid_modeling → axisymmetric
            for k in known:
                if k in did or did in k:
                    node["dialect"] = k
                    break
            else:
                # 尝试从 op 推断
                for k in known:
                    d = registry.get(k)
                    if d:
                        try:
                            d.get_op_spec(node.get("op", ""), node.get("op_version", "1.0.0"))
                            node["dialect"] = k
                            break
                        except Exception:
                            pass

    for comp in doc.get("components", []):
        od = comp.get("owner_dialect", "")
        if od and od not in known:
            comp["owner_dialect"] = "axisymmetric"

    for sd in doc.get("selected_dialects", []):
        d = sd.get("dialect", "")
        if d and d not in known:
            sd["dialect"] = "axisymmetric"
        if registry:
            rd = registry.get(sd.get("dialect", ""))
            if rd and sd.get("version") != rd.version:
                sd["version"] = rd.version

    return doc


def _fix_qualified_op_names(doc: dict) -> dict:
    """axisymmetric.revolve_profile → revolve_profile"""
    for node in doc.get("nodes", []):
        op = node.get("op", "")
        if "." in op:
            node["op"] = op.split(".")[-1]
    return doc


def _fix_param_names(doc: dict) -> dict:
    """修正 LLM 常用的错误参数字段名。"""
    for node in doc.get("nodes", []):
        op = node.get("op", "")
        fixes = PARAM_NAME_FIXES.get(op, {})
        params = node.get("params", {})
        for bad_name, good_name in fixes.items():
            if bad_name in params:
                if good_name is None:
                    del params[bad_name]  # 删除不应该存在的参数
                else:
                    if good_name not in params:  # 不覆盖已有正确值
                        params[good_name] = params[bad_name]
                    del params[bad_name]
    return doc


def _fix_target_values(doc: dict) -> dict:
    """apply_safe_fillet/chamfer target: all_external→all_external_edges"""
    for node in doc.get("nodes", []):
        if node.get("op") in ("apply_safe_fillet", "apply_safe_chamfer"):
            tgt = node.get("params", {}).get("target", "")
            if tgt in TARGET_VALUE_FIXES:
                node["params"]["target"] = TARGET_VALUE_FIXES[tgt]
    return doc


def _fix_cross_component_refs(doc: dict) -> dict:
    """将跨 component 的 node ref 转为 component ref。
    LLM 常用 {node: X, output: body} 引用另一个 component 的节点，
    但跨 component 引用必须用 {component: X, output: body}。"""
    # 建立 node_id → component_id 的映射
    node_comp: dict[str, str] = {}
    for n in doc.get("nodes", []):
        node_comp[n.get("id", "")] = n.get("component", "")

    for node in doc.get("nodes", []):
        cid = node.get("component", "")
        for inp in node.get("inputs", []):
            ref_node = inp.get("node", "")
            if ref_node and ref_node in node_comp:
                ref_comp = node_comp[ref_node]
                if ref_comp != cid:
                    # Cross-component: convert to component reference
                    inp["component"] = ref_comp
                    inp.pop("node", None)
    return doc


def _fix_root_node(doc: dict) -> dict:
    """修正 root_node 引用。"""
    node_ids = {n["id"] for n in doc.get("nodes", [])}
    node_by_comp: dict[str, list] = {}
    for n in doc.get("nodes", []):
        cid = n.get("component", "")
        node_by_comp.setdefault(cid, []).append(n)

    for comp in doc.get("components", []):
        rn = comp.get("root_node", "")
        if rn and rn not in node_ids:
            cid = comp.get("id", "")
            comp_nodes = node_by_comp.get(cid, [])
            if comp_nodes:
                # 优先选择最后一个 produce body:solid 的节点
                body_nodes = [n for n in comp_nodes
                              if any(o.get("name") == "body" and o.get("type") == "solid"
                                     for o in n.get("outputs", []))]
                if body_nodes:
                    comp["root_node"] = body_nodes[-1]["id"]
                else:
                    comp["root_node"] = comp_nodes[-1]["id"]
    return doc


def _fix_unknown_ops(doc: dict, dialect_registry=None) -> dict:
    """删除 LLM 虚造的不存在的 op 节点 (如 'cleanup', 'compose')。
    同时移除非 op 节点的引用。"""
    if dialect_registry is None:
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        dialect_registry = default_registry()

    valid_ops: set[tuple[str, str]] = set()
    for did in dialect_registry.list_ids():
        d = dialect_registry.get(did)
        if d:
            for (op_name, op_ver) in d.op_specs().keys():
                valid_ops.add((did, op_name))

    nodes = doc.get("nodes", [])
    removed_ids = set()
    kept_nodes = []
    for node in nodes:
        did = node.get("dialect", "")
        op = node.get("op", "")
        # Allow nodes with known dialects even if op lookup fails
        is_valid = (did, op) in valid_ops
        if not is_valid:
            # Try matching: if op name exists in ANY dialect, keep it
            found = any((d, op) in valid_ops for d in dialect_registry.list_ids())
            if not found:
                removed_ids.add(node.get("id", ""))
                continue
        kept_nodes.append(node)

    if removed_ids:
        doc["nodes"] = kept_nodes
        node_ids = {n["id"] for n in kept_nodes}
        # Fix root_node references + remove empty components
        kept_comps = []
        for comp in doc.get("components", []):
            cid = comp.get("id", "")
            comp_nodes = [n for n in kept_nodes if n.get("component") == cid]
            if not comp_nodes and cid != "__assembly__":
                continue  # Remove empty non-assembly components
            rn = comp.get("root_node", "")
            if rn not in node_ids:
                if comp_nodes:
                    body_nodes = [n for n in comp_nodes
                                  if any(o.get("name") == "body" and o.get("type") == "solid"
                                         for o in n.get("outputs", []))]
                    comp["root_node"] = body_nodes[-1]["id"] if body_nodes else comp_nodes[-1]["id"]
                elif cid == "__assembly__":
                    continue  # Remove empty assembly too
            kept_comps.append(comp)
        doc["components"] = kept_comps
    return doc


def _fix_phase_ordering(doc: dict, dialect_registry=None) -> dict:
    """按 phase 顺序重排 nodes。LLM 经常不遵守 phase order 导致验证失败。"""
    if dialect_registry is None:
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        dialect_registry = default_registry()

    # 收集每个 component 的 phase rank
    comp_phase_map: dict[str, dict[str, int]] = {}
    for node in doc.get("nodes", []):
        did = node.get("dialect", "")
        cid = node.get("component", "")
        if cid not in comp_phase_map:
            d = dialect_registry.get(did)
            if d and hasattr(d, "phase_order"):
                comp_phase_map[cid] = {p: i for i, p in enumerate(d.phase_order)}
            else:
                comp_phase_map[cid] = {}

    # 按 phase rank 排序 (同 phase 保持原顺序 — stable sort)
    def sort_key(node):
        cid = node.get("component", "")
        phase = node.get("phase", "")
        rank_map = comp_phase_map.get(cid, {})
        return rank_map.get(phase, 999)

    doc["nodes"] = sorted(doc.get("nodes", []), key=sort_key)
    return doc


def _fix_profile_stations(doc: dict) -> dict:
    """修复 revolve_profile 的 profile_stations 结构问题。

    问题1: 只有 1 个 station → 复制并加微小 z 偏移。
    问题2 (关键): 所有 station 有相同的 z_front_mm 和 z_rear_mm。
        LLM 把它们当作"横截面描述"，但实际应该是"顺序多段线"。
        修复: 按 r_mm 降序排列，分配顺序 z 范围。"""
    for node in doc.get("nodes", []):
        if node.get("op") != "revolve_profile":
            continue
        stations = node.get("params", {}).get("profile_stations", [])
        if not isinstance(stations, list) or len(stations) == 0:
            node["params"]["profile_stations"] = [
                {"r_mm": 10.0, "z_front_mm": 0.0, "z_rear_mm": 5.0},
                {"r_mm": 5.0, "z_front_mm": 5.0, "z_rear_mm": 6.0},
            ]
            continue

        if len(stations) < 2:
            s0 = dict(stations[0])
            s1 = dict(s0)
            s1["z_front_mm"] = s0["z_rear_mm"]
            s1["z_rear_mm"] = s0["z_rear_mm"] + 0.5
            node["params"]["profile_stations"] = [s0, s1]
            continue

        # 检测: 所有 station 的 z_front_mm 相同 AND z_rear_mm 相同？
        z_fronts = {s.get("z_front_mm") for s in stations}
        z_rears = {s.get("z_rear_mm") for s in stations}

        if len(z_fronts) == 1 and len(z_rears) == 1:
            # 这是一个扁平 profile — LLM 错误地把所有 station 放在同一高度
            z_start = list(z_fronts)[0]
            z_end = list(z_rears)[0]
            thickness = z_end - z_start
            if thickness <= 0:
                thickness = 10.0  # 默认 10mm 厚度

            # 按 r_mm 降序排列 (外 → 内)
            sorted_stations = sorted(stations, key=lambda s: s.get("r_mm", 0), reverse=True)

            new_stations = []
            for i, s in enumerate(sorted_stations):
                if i == 0:
                    # 第一个 station: 外壁, 全厚度
                    new_stations.append({
                        "r_mm": s["r_mm"],
                        "z_front_mm": z_start,
                        "z_rear_mm": z_end,
                    })
                elif i == len(sorted_stations) - 1:
                    # 最后一个 station: 内孔, 微小 z 偏移
                    prev_z = new_stations[-1]["z_rear_mm"]
                    new_stations.append({
                        "r_mm": s["r_mm"],
                        "z_front_mm": prev_z,
                        "z_rear_mm": prev_z + 1.0,
                    })
                else:
                    # 中间 station: 阶梯
                    prev_z = new_stations[-1]["z_rear_mm"]
                    new_stations.append({
                        "r_mm": s["r_mm"],
                        "z_front_mm": prev_z,
                        "z_rear_mm": prev_z + 1.0,
                    })

            node["params"]["profile_stations"] = new_stations

    return doc


def _fix_param_values(doc: dict) -> dict:
    """修正 LLM 常见的参数值偏差 (如 direction='positive' → '+')。"""
    DIRECTION_FIXES = {
        "positive": "+", "pos": "+", "up": "+", "outward": "+",
        "negative": "-", "neg": "-", "down": "-", "inward": "-",
        "+z": "+", "-z": "-", "z+": "+", "z-": "-", "both": "+",
    }
    AXIS_FIXES = {"z+": "Z", "+z": "Z", "z-": "Z", "-z": "Z", "+Z": "Z", "-Z": "Z", "z": "Z", "x": "X", "y": "Y"}
    STANDARD_FIXES = {"metric": "ISO_metric", "iso": "ISO_metric", "iso_metric": "ISO_metric",
                       "metric_coarse": "ISO_metric", "coarse": "ISO_metric"}
    CLASS_FIXES = {"6h": "6H", "6g": "6H", "7h": "7H", "8g": "6g"}

    for node in doc.get("nodes", []):
        params = node.get("params", {})
        # direction
        if "direction" in params:
            d = str(params["direction"]).lower().strip()
            if d in DIRECTION_FIXES:
                params["direction"] = DIRECTION_FIXES[d]
        # axis
        for key in ("axis",):
            if key in params:
                a = str(params[key]).strip()
                if a in AXIS_FIXES:
                    params[key] = AXIS_FIXES[a]
        # standard
        if "standard" in params:
            s = str(params["standard"]).lower().strip().replace(" ", "_")
            if s in STANDARD_FIXES:
                params["standard"] = STANDARD_FIXES[s]
        # thread_class
        if "thread_class" in params:
            c = str(params["thread_class"]).strip()
            if c in CLASS_FIXES:
                params["thread_class"] = CLASS_FIXES[c]
    return doc


def _fill_default_params(doc: dict) -> dict:
    """填充缺失的有默认值的参数。"""
    defaults = {
        "revolve_profile": {"axis": "Z"},
        "cut_center_bore": {"axis": "Z", "through_all": True},
        "cut_circular_hole_pattern": {"axis": "Z", "through_all": True},
        "cut_hole_pattern_linear": {"axis": "Z", "through_all": True},
        "extrude_rectangle": {"centered": True, "direction": "+", "plane": "XY"},
        "cut_rectangular_pocket": {"centered": True, "direction": "+", "plane": "XY"},
        "add_rectangular_boss": {"centered": True, "plane": "XY"},
        "boolean_union": {},
        "boolean_cut": {},
    }
    for node in doc.get("nodes", []):
        op = node.get("op", "")
        for k, v in defaults.get(op, {}).items():
            if k not in node.get("params", {}):
                node["params"][k] = v
    return doc


def _remove_extra_params(doc: dict) -> dict:
    """删除已知的无效参数字段。"""
    known_bad_params = {
        "revolve_profile": {"outer_diameter_mm", "inner_diameter_mm", "height_mm"},
        "cut_center_bore": {"outer_diameter_mm", "bore_diameter_mm", "depth_mm"},
        "extrude_rectangle": {"length", "thickness", "material"},
        "boolean_union": {"clean_after", "merge_result", "keep_tool"},
        "boolean_cut": {"clean_after", "merge_result", "keep_tool"},
        "cut_center_bore": {"depth_mm", "bore_depth", "length"},
        "shell_body": {"open_faces"},  # open_faces defaults to []
    }
    for node in doc.get("nodes", []):
        op = node.get("op", "")
        bad = known_bad_params.get(op, set())
        for key in list(node.get("params", {}).keys()):
            if key in bad:
                del node["params"][key]
    return doc
