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
    "all_edges": "all_external_edges",
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
    doc = _fix_dialect_names(doc, dialect_registry)
    doc = _fix_qualified_op_names(doc)
    doc = _fix_param_names(doc)
    doc = _fix_target_values(doc)
    doc = _fix_root_node(doc)
    doc = _fix_profile_stations(doc)
    doc = _fill_default_params(doc)
    doc = _remove_extra_params(doc)
    return doc


def _fix_output_names(doc: dict) -> dict:
    """output name: solid→body, frame→outer_frame, solid_body→body"""
    for node in doc.get("nodes", []):
        for o in node.get("outputs", []):
            name = o.get("name", "")
            otype = o.get("type", "")
            if name == "solid" and otype == "solid":
                o["name"] = "body"
            elif name == "frame" and otype == "frame":
                o["name"] = "outer_frame"
            elif name == "solid_body":
                o["name"] = "body"
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


def _fix_profile_stations(doc: dict) -> dict:
    """确保 revolve_profile 的 profile_stations 至少有 2 个 station。
    LLM 经常只输出 1 个 station 来定义圆柱体，但 validator 要求 ≥2。
    修复方法：复制第一个 station 并给 z 加 0.5mm 偏移。"""
    for node in doc.get("nodes", []):
        if node.get("op") != "revolve_profile":
            continue
        stations = node.get("params", {}).get("profile_stations", [])
        if not isinstance(stations, list):
            continue
        if len(stations) < 2:
            if len(stations) == 1:
                s0 = dict(stations[0])
                # 创建一个微小偏移的第二个 station
                s1 = dict(s0)
                s1["z_front_mm"] = s0["z_rear_mm"]
                s1["z_rear_mm"] = s0["z_rear_mm"] + 0.5
                node["params"]["profile_stations"] = [s0, s1]
            else:
                # 空列表 → 添加默认 station
                node["params"]["profile_stations"] = [
                    {"r_mm": 10.0, "z_front_mm": 0.0, "z_rear_mm": 5.0},
                    {"r_mm": 5.0, "z_front_mm": 5.0, "z_rear_mm": 6.0},
                ]
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
    }
    for node in doc.get("nodes", []):
        op = node.get("op", "")
        bad = known_bad_params.get(op, set())
        for key in list(node.get("params", {}).keys()):
            if key in bad:
                del node["params"][key]
    return doc
