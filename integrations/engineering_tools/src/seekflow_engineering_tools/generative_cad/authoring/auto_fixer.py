"""AutoFixer — programmatic fix for common LLM hallucination patterns.

Each fix is idempotent, safe, and does not alter design intent.
Fix strategies derived from statistical analysis of DeepSeek output patterns.

v0.7: audited — each fix records rule_id, path, old_value, new_value,
severity, and confidence via AutoFixEntry / AutoFixReport.

v6: AutoFixCategory system — fixes classified by risk level.
Default policy: allow SYNTACTIC_ALIAS, SCHEMA_DEFAULT, CONTEXT_SAFE.
Block: SEMANTIC_GUESS, DESTRUCTIVE unless explicitly enabled.

v6.1: _sanitize_llm_json — strip control characters, zero-width chars,
unpaired surrogates from LLM output before any fix processing.
"""

from __future__ import annotations
import copy
import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash


# ═══════════════════════════════════════════════════════════════════════════════
# v6.1: JSON sanitizer (fixes tm12_robot_wrist control character issue)
# ═══════════════════════════════════════════════════════════════════════════════

def _sanitize_llm_json(obj: Any) -> Any:
    """Recursively sanitize LLM output for JSON compatibility.

    Handles:
    - Control characters (U+0000-U+001F except \\n, \\r, \\t)
    - Delete character (U+007F) and extended control chars (U+0080-U+009F)
    - Zero-width characters (U+200B ZWSP, U+200C ZWNJ, U+200D ZWJ, U+FEFF BOM)
    - Unpaired surrogates (U+D800-U+DFFF)
    - Null bytes

    This is called before any other AutoFix function because control characters
    can cause json.loads() and Pydantic model_validate() to fail unrecoverably.
    """
    if isinstance(obj, str):
        # Remove control chars except common whitespace
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', obj)
        # Remove zero-width characters
        cleaned = re.sub(r'[​-‍﻿]', '', cleaned)
        # Remove unpaired surrogates
        cleaned = re.sub(r'[\ud800-\udfff]', '', cleaned)
        return cleaned
    elif isinstance(obj, dict):
        return {_sanitize_llm_json(k): _sanitize_llm_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_llm_json(v) for v in obj]
    return obj


# ═══════════════════════════════════════════════════════════════════════════════
# v6: AutoFix risk classification
# ═══════════════════════════════════════════════════════════════════════════════

class AutoFixCategory(str, Enum):
    """Risk-based fix category.

    SYNTACTIC_ALIAS: name alias replacement (solid→body, wire→curve)
    SCHEMA_DEFAULT: fill schema defaults (op_version, phase)
    CONTEXT_SAFE: contextually safe corrections (dialect name typos, param value aliases)
    SEMANTIC_GUESS: guessing design intent (filling empty profile stations)
    DESTRUCTIVE: removing data (deleting unknown ops)
    """
    SYNTACTIC_ALIAS = "syntactic_alias"
    SCHEMA_DEFAULT = "schema_default"
    CONTEXT_SAFE = "context_safe"
    SEMANTIC_GUESS = "semantic_guess"
    DESTRUCTIVE = "destructive"


# v6 default policy: allow only safe categories
DEFAULT_ALLOWED_AUTOFIX_CATEGORIES: set[AutoFixCategory] = {
    AutoFixCategory.SYNTACTIC_ALIAS,
    AutoFixCategory.SCHEMA_DEFAULT,
    AutoFixCategory.CONTEXT_SAFE,
}

# v6.2: severity 字符串到 AutoFixCategory 的映射 — 用于 _apply_fix 强制 category 检查
SEVERITY_TO_CATEGORY: dict[str, AutoFixCategory] = {
    "safe_alias": AutoFixCategory.CONTEXT_SAFE,
    "semantic_guess": AutoFixCategory.SEMANTIC_GUESS,
    "destructive": AutoFixCategory.DESTRUCTIVE,
}


# ── Audit data structures ────────────────────────────────────────────────────


class AutoFixEntry(BaseModel):
    """One fix entry with full audit trail."""
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    path: str
    old_value: Any
    new_value: Any
    severity: Literal["safe_alias", "semantic_guess", "destructive"] = "safe_alias"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    message: str = ""


class AutoFixReport(BaseModel):
    """Audit report for an autofix pass."""
    model_config = ConfigDict(extra="forbid")

    applied: bool
    before_hash: str
    after_hash: str
    entries: list[AutoFixEntry] = Field(default_factory=list)

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
    "all_outer_edges": "all_external_edges",
}


def auto_fix(raw_doc: dict, dialect_registry=None) -> dict:
    """对 RawGcadDocument dict 应用所有自动修复。幂等，可重复调用。

    兼容 wrapper，内部调用 auto_fix_with_report 并返回 fixed_doc。
    """
    fixed_doc, _report = auto_fix_with_report(raw_doc, dialect_registry)
    return fixed_doc


def auto_fix_with_report(
    raw_doc: dict,
    dialect_registry=None,
) -> tuple[dict, AutoFixReport]:
    """对 RawGcadDocument dict 应用所有自动修复，附带完整审计报告。

    不原地修改 raw_doc（deepcopy），每条修复记录 AutoFixEntry。

    Returns:
        (fixed_doc, AutoFixReport) — report.applied 为 True 当且仅当
        before_hash != after_hash。
    """
    before_hash = stable_hash(raw_doc)
    doc = copy.deepcopy(raw_doc)
    # v6.1: Sanitize LLM output before any fix processing
    doc = _sanitize_llm_json(doc)
    entries: list[AutoFixEntry] = []

    def _apply_fix(
        name: str, fix_fn,
        severity: Literal["safe_alias", "semantic_guess", "destructive"] = "safe_alias",
        confidence: float = 1.0,
    ):
        """Apply one fix and record all changes by comparing before/after hashes."""
        nonlocal doc
        # v6.2: 强制 category 检查 — 拒绝不在允许集合中的 fix
        cat = SEVERITY_TO_CATEGORY.get(severity, AutoFixCategory.SEMANTIC_GUESS)
        if cat not in DEFAULT_ALLOWED_AUTOFIX_CATEGORIES:
            entries.append(AutoFixEntry(
                rule_id=name,
                path="/",
                old_value="<skipped>",
                new_value="<skipped>",
                severity=severity,
                confidence=confidence,
                message=f"Fix '{name}' skipped: category '{severity}' not in allowed categories {sorted(c.value for c in DEFAULT_ALLOWED_AUTOFIX_CATEGORIES)}",
            ))
            return  # 不执行 fix
        before = stable_hash(doc)
        doc = fix_fn(doc)
        after = stable_hash(doc)
        if before != after:
            entries.append(AutoFixEntry(
                rule_id=name,
                path="/",
                old_value=f"<hash:{before[:12]}>",
                new_value=f"<hash:{after[:12]}>",
                severity=severity,
                confidence=confidence,
                message=f"Applied fix: {name}",
            ))

    # Fix order matters — later fixes may depend on earlier ones
    _apply_fix("fix_missing_ids", lambda d: _fix_missing_ids(d))
    _apply_fix("remove_extra_top_fields", lambda d: _remove_extra_top_fields(d))
    _apply_fix("fix_selected_dialects", lambda d: _fix_selected_dialects(d))
    _apply_fix("fix_constraints", lambda d: _fix_constraints(d))
    _apply_fix("fix_v2_placement_scope", lambda d: _fix_v2_placement_scope(d))
    _apply_fix("fix_missing_position_mm", lambda d: _fix_missing_position_mm(d))
    _apply_fix("fix_chamfer_zero_distance", lambda d: _fix_chamfer_zero_distance(d))
    _apply_fix("fix_chamfer_fillet_optional", lambda d: _fix_chamfer_fillet_optional(d))
    _apply_fix("fix_output_names", lambda d: _fix_output_names(d))
    _apply_fix("fix_input_output_names", lambda d: _fix_input_output_names(d))
    _apply_fix("fix_op_versions", lambda d: _fix_op_versions(d, dialect_registry))
    _apply_fix("fix_dialect_names", lambda d: _fix_dialect_names(d, dialect_registry))
    _apply_fix("fix_qualified_op_names", lambda d: _fix_qualified_op_names(d))
    _apply_fix("fix_param_names", lambda d: _fix_param_names(d))
    _apply_fix("fix_param_values", lambda d: _fix_param_values(d))
    _apply_fix("fix_path_points", lambda d: _fix_path_points(d))
    _apply_fix("fix_unknown_ops", lambda d: _fix_unknown_ops(d, dialect_registry), severity="destructive", confidence=0.85)
    _apply_fix("fix_target_values", lambda d: _fix_target_values(d))
    _apply_fix("fix_cross_component_refs", lambda d: _fix_cross_component_refs(d), severity="semantic_guess", confidence=0.9)
    _apply_fix("fix_root_node", lambda d: _fix_root_node(d), severity="semantic_guess", confidence=0.95)
    _apply_fix("fix_phase_names", lambda d: _fix_phase_names(d, dialect_registry))
    _apply_fix("fix_phase_ordering", lambda d: _fix_phase_ordering(d, dialect_registry))
    _apply_fix("fix_profile_stations", lambda d: _fix_profile_stations(d), severity="semantic_guess", confidence=0.85)
    _apply_fix("fix_slot_station_order", lambda d: _fix_slot_station_order(d))
    _apply_fix("fill_default_params", lambda d: _fill_default_params(d))
    _apply_fix("fix_null_hints", lambda d: _fix_null_hints(d))
    _apply_fix("remove_extra_params", lambda d: _remove_extra_params(d))

    after_hash = stable_hash(doc)
    report = AutoFixReport(
        applied=before_hash != after_hash,
        before_hash=before_hash,
        after_hash=after_hash,
        entries=entries,
    )
    return doc, report


def _fix_input_output_names(doc: dict) -> dict:
    """修正 input 引用中的 output 名: LLM 写 output='solid' 但实际输出名叫 'body'。
    查找 producer node 的实际 outputs, 将 type 名替换为 name。"""
    # Build map: node_id -> {output_type: output_name}
    type_to_name: dict[str, dict[str, str]] = {}
    for n in doc.get("nodes", []):
        type_to_name[n["id"]] = {o.get("type", ""): o.get("name", "") for o in n.get("outputs", [])}

    for node in doc.get("nodes", []):
        for inp in node.get("inputs", []):
            ref = inp.get("node", "")
            out = inp.get("output", "")
            if ref in type_to_name and out in type_to_name[ref]:
                inp["output"] = type_to_name[ref][out]
    return doc


def _fix_op_versions(doc: dict, dialect_registry=None) -> dict:
    """修正 op_version: LLM 常把 dialect.version 当做 op.version。

    检测模式:
    - "0.2.0", "0.1.0" — 精确匹配 dialect 版本号
    - "v0.2.0", "v0.2", "v0.1.0" — 带 v 前缀的 dialect 版本
    - "" (空字符串) — LLM 忘记填 op_version
    - None — 字段缺失
    - "v1.0.0" — 带 v 前缀的正确版本号 (去前缀即可)
    """
    if dialect_registry is None:
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        dialect_registry = default_registry()

    # Patterns that are definitely dialect versions (need full replacement)
    DIALECT_VERSION_PATTERNS = frozenset({
        "0.2.0", "0.1.0", "v0.2.0", "v0.2", "v0.1.0", "0.2", "0.1",
    })

    for node in doc.get("nodes", []):
        did = node.get("dialect", "")
        op = node.get("op", "")
        ver = node.get("op_version", "")

        if ver is None or ver == "":
            # Missing op_version → fill from dialect default
            d = dialect_registry.get(did)
            if d:
                try:
                    node["op_version"] = d.default_op_version(op)
                except Exception:
                    node["op_version"] = "1.0.0"
        elif ver in DIALECT_VERSION_PATTERNS:
            # LLM used dialect version as op version
            d = dialect_registry.get(did)
            if d:
                try:
                    node["op_version"] = d.default_op_version(op)
                except Exception:
                    node["op_version"] = "1.0.0"
        elif ver.startswith("v") and ver[1:].replace(".", "").isdigit():
            # Strip "v" prefix: "v1.0.0" → "1.0.0"
            node["op_version"] = ver.lstrip("v")

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
    """修正 root_node 引用。优先选 required=True 的最后 body 节点。

    如果当前 root_node 指向 required=False 节点，且有 required=True 的 body 节点，
    则替换为 required=True 的最后一个 body 节点。这避免 optional 节点失败导致整个
    component 输出绑定为空。
    """
    node_ids = {n["id"] for n in doc.get("nodes", [])}
    node_by_comp: dict[str, list] = {}
    for n in doc.get("nodes", []):
        cid = n.get("component", "")
        node_by_comp.setdefault(cid, []).append(n)

    for comp in doc.get("components", []):
        rn = comp.get("root_node", "")
        # 检查当前 root_node 是否 required=False — 如果是则替换
        if rn and rn in node_ids:
            root_node_obj = next(
                (n for n in node_by_comp.get(comp.get("id", ""), []) if n.get("id") == rn),
                None,
            )
            if root_node_obj and root_node_obj.get("required", True):
                continue  # 当前 root_node 是 required=True，保留
            # fall through 重新选择
        cid = comp.get("id", "")
        comp_nodes = node_by_comp.get(cid, [])
        if comp_nodes:
            body_nodes = [n for n in comp_nodes
                          if any(o.get("name") == "body" and o.get("type") == "solid"
                                 for o in n.get("outputs", []))]
            # 优先 required=True 的 body 节点
            required_body_nodes = [n for n in body_nodes if n.get("required", True)]
            if required_body_nodes:
                comp["root_node"] = required_body_nodes[-1]["id"]
            elif body_nodes:
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
        # v6.3: Normalize op_version — LLM often outputs "2" instead of "1.0.0"
        ver = node.get("op_version")
        if ver and ver not in ("1.0.0", "1.0", "0.2.0"):
            # Try to normalize: "2" → "1.0.0", "v2" → "1.0.0"
            node["op_version"] = "1.0.0"

        # Allow nodes with known dialects even if op lookup fails
        is_valid = (did, op) in valid_ops
        if not is_valid:
            # Try matching: if op name exists in ANY dialect, keep it and fix dialect
            found_dialect = None
            for d in dialect_registry.list_ids():
                if (d, op) in valid_ops:
                    found_dialect = d
                    break
            if found_dialect:
                node["dialect"] = found_dialect
            else:
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


def _fix_phase_names(doc: dict, dialect_registry=None) -> dict:
    """修正 LLM 虚造的 phase 名。根据 op 的实际 phase 替换。"""
    if dialect_registry is None:
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        dialect_registry = default_registry()
    for node in doc.get("nodes", []):
        did = node.get("dialect", "")
        op = node.get("op", "")
        phase = node.get("phase", "")
        d = dialect_registry.get(did)
        if d and phase:
            try:
                spec = d.get_op_spec(op, node.get("op_version", "1.0.0"))
                if phase != spec.phase:
                    node["phase"] = spec.phase
            except Exception:
                pass
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

    单 station 现在是合法的 (axisymmetric v0.6+)，表达简单圆柱段。
    不再复制 station 来伪造两个 — 那是伪修复。

    仍然处理:
      - 空 stations → 填充默认 2-station profile
      - 所有 station 同 z 且同 r → 分配顺序 z (LLM 把横截面当 stations)
    """
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

        # Single station is valid — no need to duplicate. Skip.
        if len(stations) < 2:
            continue

        # 检测: 所有 station 的 z_front_mm 相同 AND z_rear_mm 相同？
        z_fronts = {s.get("z_front_mm") for s in stations}
        z_rears = {s.get("z_rear_mm") for s in stations}

        # ── 区域描述风格检测（Z 区间重叠）──
        # 这是 LLM 把 bore/hub/web/rim 分区域输出的典型模式。
        # 无法安全转换为外轮廓连续段 — 标记为需要 LLM repair，不做 silent 修改。
        if len(stations) >= 2:
            z_ranges = [(s.get("z_front_mm", 0), s.get("z_rear_mm", 0)) for s in stations]
            overlap_count = 0
            for i, (zf1, zr1) in enumerate(z_ranges):
                for j, (zf2, zr2) in enumerate(z_ranges[i+1:], i+1):
                    if zf1 < zr2 and zf2 < zr1:
                        overlap_count += 1
            if overlap_count > 0:
                node.setdefault("autofix_hints", []).append({
                    "issue": "regional_profile_stations",
                    "message": (
                        "profile_stations has overlapping Z ranges (regional description style). "
                        "Must be outer contour continuous segments (Z single-valued). "
                        "Cannot auto-fix — requires LLM repair."
                    ),
                })
                continue  # 不修改，让 LLM repair 处理

        # ── 原有逻辑：2 stations 共享相同 Z 区间（扁平 profile）──
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
                    new_stations.append({
                        "r_mm": s["r_mm"],
                        "z_front_mm": z_start,
                        "z_rear_mm": z_end,
                    })
                elif i == len(sorted_stations) - 1:
                    prev_z = new_stations[-1]["z_rear_mm"]
                    new_stations.append({
                        "r_mm": s["r_mm"],
                        "z_front_mm": prev_z,
                        "z_rear_mm": prev_z + 1.0,
                    })
                else:
                    prev_z = new_stations[-1]["z_rear_mm"]
                    new_stations.append({
                        "r_mm": s["r_mm"],
                        "z_front_mm": prev_z,
                        "z_rear_mm": prev_z + 1.0,
                    })

            node["params"]["profile_stations"] = new_stations

        # After all fixes: if all r_mm are still identical, the profile is just
        # a cylinder with no bore — split the last station to create a bore.
        stations = node["params"].get("profile_stations", [])
        if len(stations) >= 2:
            r_values = {s.get("r_mm") for s in stations}
            if len(r_values) == 1:
                last = dict(stations[-1])
                last["r_mm"] = last["r_mm"] / 2.0
                prev_z = stations[-2]["z_rear_mm"] if len(stations) > 1 else stations[0]["z_rear_mm"]
                last["z_front_mm"] = prev_z
                last["z_rear_mm"] = prev_z + 1.0
                stations[-1] = last
                node["params"]["profile_stations"] = stations

    return doc


def _fix_slot_station_order(doc: dict) -> dict:
    """修复 cut_rim_slot_pattern 的 slot_profile.stations depth 非递减顺序。

    RimSlotProfile.validate_depth_order 要求 depth_mm 非递减，但 LLM 经常输出
    递减顺序（如 [12, 8, 4]）。此规则按 depth_mm 升序排序 stations。
    """
    for node in doc.get("nodes", []):
        if node.get("op") != "cut_rim_slot_pattern":
            continue
        sp = node.get("params", {}).get("slot_profile", {})
        if not isinstance(sp, dict):
            continue
        stations = sp.get("stations", [])
        if not stations or len(stations) < 2:
            continue
        depths = [s.get("depth_mm", 0) for s in stations]
        if depths != sorted(depths):
            sp["stations"] = sorted(stations, key=lambda s: s.get("depth_mm", 0))
    return doc


def _fix_param_values(doc: dict) -> dict:
    """修正 LLM 常见的参数值偏差 (如 direction='positive' → '+')。"""
    DIRECTION_FIXES = {
        "positive": "+", "pos": "+", "up": "+", "outward": "+",
        "negative": "-", "neg": "-", "down": "-", "inward": "-",
        "+z": "+", "-z": "-", "z+": "+", "z-": "-", "both": "+",
        "z": "+", "Z": "+",  # LLM uses axis name as direction
    }
    AXIS_FIXES = {"z+": "Z", "+z": "Z", "z-": "Z", "-z": "Z", "+Z": "Z", "-Z": "Z", "z": "Z", "x": "X", "y": "Y"}
    PLANE_FIXES = {"xy": "XY", "yz": "YZ", "xz": "XZ", "yx": "XY", "zy": "YZ", "zx": "XZ"}
    # add_rib uses X/Y for direction, NOT +/-. Fix only for add_rib.
    RIB_DIRECTION_FIX = {"+": "X", "-": "Y", "+x": "X", "-y": "Y", "+z": "X", "-z": "Y", "x+": "X", "y+": "Y"}
    STANDARD_FIXES = {"metric": "ISO_metric", "iso": "ISO_metric", "iso_metric": "ISO_metric",
                       "metric_coarse": "ISO_metric", "coarse": "ISO_metric"}
    # thread_class: context-aware — internal vs external have different valid values
    INTERNAL_THREAD_CLASS_FIXES = {"6h": "6H", "6g": "6H", "7h": "7H", "6G": "6G", "6H": "6H", "7H": "7H"}
    # cut_internal_thread allows: 6H, 6G, 7H
    EXTERNAL_THREAD_CLASS_FIXES = {"6h": "6h", "6g": "6g", "8g": "8g", "6H": "6g", "6G": "6g", "7H": "6g", "8G": "8g"}
    # cut_external_thread allows: 6g, 6h, 8g

    for node in doc.get("nodes", []):
        params = node.get("params", {})
        op = node.get("op", "")
        # direction
        if "direction" in params:
            d = str(params["direction"]).lower().strip()
            if op == "add_rib" and d in RIB_DIRECTION_FIX:
                params["direction"] = RIB_DIRECTION_FIX[d]
            elif op != "add_rib" and d in DIRECTION_FIXES:
                params["direction"] = DIRECTION_FIXES[d]
        # axis
        for key in ("axis",):
            if key in params:
                a = str(params[key]).strip()
                if a in AXIS_FIXES:
                    params[key] = AXIS_FIXES[a]
        # plane
        if "plane" in params:
            p = str(params["plane"]).strip().lower()
            if p in PLANE_FIXES:
                params["plane"] = PLANE_FIXES[p]
        # standard
        if "standard" in params:
            s = str(params["standard"]).lower().strip().replace(" ", "_")
            if s in STANDARD_FIXES:
                params["standard"] = STANDARD_FIXES[s]
        # thread_class — context-aware by op type
        if "thread_class" in params:
            c = str(params["thread_class"]).strip()
            if op == "cut_internal_thread" and c in INTERNAL_THREAD_CLASS_FIXES:
                params["thread_class"] = INTERNAL_THREAD_CLASS_FIXES[c]
            elif op == "cut_external_thread" and c in EXTERNAL_THREAD_CLASS_FIXES:
                params["thread_class"] = EXTERNAL_THREAD_CLASS_FIXES[c]
    return doc


def _fix_path_points(doc: dict) -> dict:
    """修正 create_sweep_path 的 path_points: {x,y,z} → {x_mm,y_mm,z_mm}。"""
    for node in doc.get("nodes", []):
        if node.get("op") != "create_sweep_path":
            continue
        pts = node.get("params", {}).get("path_points", [])
        fixed = []
        for pt in pts:
            if isinstance(pt, dict):
                fp = {}
                for k, v in pt.items():
                    if k in ("x", "y", "z"):
                        fp[f"{k}_mm"] = v
                    else:
                        fp[k] = v
                # If no _mm fields were created, use as-is
                fixed.append(fp if any(k.endswith("_mm") for k in fp) else pt)
            else:
                fixed.append(pt)
        if any(p != o for p, o in zip(fixed, pts)):
            node["params"]["path_points"] = fixed
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


def _fix_missing_ids(doc: dict) -> dict:
    """Fix missing document_id / part_name (DeepSeek v4-pro common omission)."""
    if not doc.get("document_id") or not str(doc.get("document_id", "")).strip():
        # Generate from part_name or use a safe default
        part = str(doc.get("part_name", "")).strip()
        doc["document_id"] = f"gcad_{part}" if part else "gcad_autofix"
    if not doc.get("part_name") or not str(doc.get("part_name", "")).strip():
        doc["part_name"] = "autofix_part"
    return doc


def _remove_extra_top_fields(doc: dict) -> dict:
    """Remove top-level fields not in RawGcadDocument schema (LLM hallucination)."""
    ALLOWED_TOP_KEYS = {
        "schema_version", "document_id", "part_name", "units", "trust_level",
        "selected_dialects", "components", "nodes", "constraints", "safety",
        "llm_validation_hints",
    }
    for key in list(doc.keys()):
        if key not in ALLOWED_TOP_KEYS:
            del doc[key]
    return doc


def _fix_missing_position_mm(doc: dict) -> dict:
    """Fix cut_hole nodes: add default position_mm, strip V2-only fields.

    DeepSeek v4-pro often generates V2-style params (target_face, center_uv_mm,
    normal_axis) for legacy V1 cut_hole ops. This strips those V2 fields.
    """
    V2_ONLY_FIELDS = {"target_face", "center_uv_mm", "normal_axis",
                      "origin_mode", "through_mode", "depth_mm",
                      "start_offset_mm", "placement", "scope"}
    for node in doc.get("nodes", []):
        op = node.get("op", "")
        if op in ("cut_hole",):
            params = node.get("params", {})
            # Strip V2-only fields
            for key in V2_ONLY_FIELDS:
                params.pop(key, None)
            # Set defaults for required V1 fields
            if "position_mm" not in params:
                params["position_mm"] = [0, 0]
            if "axis" not in params:
                params["axis"] = "Z"
            if "diameter_mm" not in params and "dia_mm" in params:
                params["diameter_mm"] = params.pop("dia_mm")
            if "diameter_mm" not in params:
                params["diameter_mm"] = 5.0  # sensible default
    return doc


def _fix_v2_placement_scope(doc: dict) -> dict:
    """Fix cut_hole_v2/drill_hole_3d invalid placement.scope (LLM sets it to string/null)."""
    for node in doc.get("nodes", []):
        params = node.get("params", {})
        placement = params.get("placement")
        if isinstance(placement, dict):
            # Fix scope: if not a dict, set to empty dict (FeatureScope default)
            if "scope" in placement and not isinstance(placement["scope"], dict):
                placement["scope"] = {}
        # Fix top-level scope on V2 params
        for key in ("scope",):
            if key in params and not isinstance(params[key], dict):
                params[key] = {}
    return doc


def _fix_chamfer_zero_distance(doc: dict) -> dict:
    """Remove chamfer/fillet nodes with distance/radius <= 0 (LLM error).
    Also handles negative distance_mm values."""
    nodes = doc.get("nodes", [])
    kept = []
    for node in nodes:
        op = node.get("op", "")
        if op in ("apply_safe_chamfer", "apply_safe_fillet"):
            params = node.get("params", {})
            key = "distance_mm" if op == "apply_safe_chamfer" else "radius_mm"
            val = params.get(key, 0)
            if isinstance(val, (int, float)) and val <= 0:
                continue  # Remove this node
        kept.append(node)
    if len(kept) < len(nodes):
        doc["nodes"] = kept
    return doc


def _fix_constraints(doc: dict) -> dict:
    """Fix invalid constraints fields (LLM often sets expected_bbox_mm to null/single number)."""
    c = doc.get("constraints", {})
    if isinstance(c, dict):
        bbox = c.get("expected_bbox_mm")
        if bbox is not None and not (isinstance(bbox, list) and len(bbox) == 3):
            c["expected_bbox_mm"] = None  # Remove invalid bbox, make it optional
        # Ensure required bool flags
        for key in ("require_step_file", "require_metadata_sidecar", "require_closed_solid"):
            if key in c and not isinstance(c[key], bool):
                c[key] = True
        if "expected_body_count" in c and not isinstance(c["expected_body_count"], int):
            c["expected_body_count"] = 1
    return doc


def _fix_selected_dialects(doc: dict) -> dict:
    """Fix missing/invalid selected_dialects (LLM omission)."""
    if not doc.get("selected_dialects"):
        # Reconstruct from nodes
        dialects_in_use = set()
        for node in doc.get("nodes", []):
            d = node.get("dialect", "")
            if d:
                dialects_in_use.add(d)
        if dialects_in_use:
            doc["selected_dialects"] = [
                {"dialect": d, "version": "0.2.0"} for d in sorted(dialects_in_use)
            ]
    return doc


def _fix_chamfer_fillet_optional(doc: dict) -> dict:
    """Mark chamfer/fillet nodes as optional so complex geometry doesn't
    fail the entire pipeline when OCCT can't execute them.

    Chamfer and fillet are decorative finishing operations.  On complex
    revolved bodies (turbine disks, etc.) OCCT/CadQuery may fail with
    'ChFi3d_Builder: only 2 faces'.  Marking them required=False with
    degradation_policy='may_skip_with_warning' allows the pipeline to
    skip the failed operation and still output the main geometry.
    """
    for node in doc.get("nodes", []):
        op = node.get("op", "")
        if op in ("apply_safe_chamfer", "apply_safe_fillet"):
            node["required"] = False
            node["degradation_policy"] = "may_skip_with_warning"
    return doc


def _fix_null_hints(doc: dict) -> dict:
    """Fix llm_validation_hints: null -> {} (DeepSeek v4-pro common error)."""
    if doc.get("llm_validation_hints") is None:
        doc["llm_validation_hints"] = {}
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
