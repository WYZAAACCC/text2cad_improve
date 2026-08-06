"""Edit 任务样本构造器（对源模型改参重生成，确定性 NL 指令，不碰主流程/src）。

对每个源任务目录选一个可用参数（PARAM_REGISTRY 语义定位），生成编辑指令
（中文 label 模板）→ regenerate_model 重建 → before/after 对比。落盘
_param_experiment/output/datasets/edit_tasks/<sample_id>.json。

用法:
  .conda/python.exe _param_experiment/run_edit_tasks.py --only mon_sweep_q2_slots_96
  .conda/python.exe _param_experiment/run_edit_tasks.py --limit 5
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
OUTPUT = ROOT / "app" / "text-to-cad" / "server" / "output"
DATASETS = _HERE / "output" / "datasets" / "edit_tasks"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from mcp_tools import (  # noqa: E402
    PARAM_REGISTRY, REGEN_WS, _current_value, _resolve_param_nodes,
    _slot_fillet_class, _slot_profile, check_slot_depth_and_rim,
    check_slot_pitch_and_ligament, regenerate_model,
)
import run_enrich  # noqa: E402

# 参数优先级（定位稳定性排序；圆角类可能不可用，靠 _resolve_param_nodes 过滤）
_PRIORITY = ["slot_count", "slot_distribution_radius", "slot_axial_depth",
             "root_fillet", "disc_hub_web_fillet", "disc_web_rim_fillet"]


def _inherit(tid: str) -> dict:
    try:
        d = json.loads((OUTPUT / tid / "dataset_enrich.json").read_text(encoding="utf-8"))
        return {"design_id": d.get("design_id"), "model_id": d.get("model_id")}
    except Exception:  # noqa: BLE001
        return {"design_id": None, "model_id": None}


def _pick_param(ir: dict):
    """按优先级选第一个定位可用的参数，返回 (reg, cur)。"""
    for pk in _PRIORITY:
        reg = next((r for r in PARAM_REGISTRY if r["param"] == pk), None)
        if reg is None:
            continue
        if _resolve_param_nodes(ir, pk):
            cur = _current_value(ir, reg)
            if cur is not None:
                return reg, cur
    return None, None


def _new_value(reg: dict, cur):
    lo, hi = reg["range"]
    v = float(cur) * 0.6
    v = max(float(lo), min(float(hi), v))
    return int(round(v)) if reg["type"] == "int" else round(v, 3)


def _constraint_keeping_updates(ir: dict) -> list:
    """P1-4 约束保持联动：槽数 ×1.25 → 分布半径按 ps=2πr/N 联动（周向节距/剩料保持）。

    论文 Edit 第 4 类"保持约束条件下的设计调整"：修改槽数但保持节距约束 ws+2cs≤ps。
    """
    pat = next((n for n in ir.get("nodes", [])
                if n.get("op") == "circular_pattern_component"), None)
    if pat is None:
        return []
    p = pat.get("params") or {}
    count, radius = p.get("count"), p.get("radius_mm")
    if not isinstance(count, (int, float)) or not isinstance(radius, (int, float)):
        return []
    nc = int(count * 1.25)
    if nc <= count:
        return []
    # 保持节距 ps = 2π·r/N 不变 → r' = r·N'/N（N 增大则 r 同步增大）
    nr = round(radius * nc / count, 3)
    return [("slot_count", nc), ("slot_distribution_radius", nr)]


def _constraint_check(base_dir: str) -> dict | None:
    """节距剩料 + 槽深轮缘厚度约束检查（before/after 对比用）。"""
    try:
        sp = check_slot_pitch_and_ligament({"base_dir": base_dir})
        sd = check_slot_depth_and_rim({"base_dir": base_dir})
        return {"ok": bool(sp.get("ok") and sd.get("ok")),
                "pitch_ligament_ok": bool(sp.get("ok")), "depth_rim_ok": bool(sd.get("ok"))}
    except Exception:  # noqa: BLE001
        return None


# ── 论文 Edit 第 4 类：添加/删除/替换局部特征（fillet_sketch）────────────────
_FILLET_ROLE_CN = {"root": "齿根", "flank": "齿面", "lobe_top": "齿顶"}


def _fillet_nodes(ir: dict) -> list:
    return [n for n in ir.get("nodes", []) if n.get("op") == "fillet_sketch"]


def _fillet_label(ir: dict, node: dict) -> str:
    if _is_disc_component(ir, node.get("component")):
        return "盘体"
    role = _slot_fillet_class(ir, node)
    return _FILLET_ROLE_CN.get(role, "局部") if role else "局部"


def _is_disc_component(ir: dict, comp_id) -> bool:
    """盘体组件判定：kind_hint 含 disc（axisymmetric_disc/turbine_disc）为盘体；
    slot/cutter 为榫槽。未知按非盘体（优先删榫槽圆角更安全）。"""
    for c in ir.get("components", []):
        if c.get("id") == comp_id:
            kh = c.get("kind_hint") or ""
            return "slot" not in kh and "cutter" not in kh
    return False


def _apply_feature_op(ir: dict, op: str) -> tuple:
    """对 IR 应用局部特征操作（fillet）。返回 (new_ir, instruction, changes) 或 (None, None, None)。"""
    ir = copy.deepcopy(ir)
    fns = _fillet_nodes(ir)
    if not fns:
        return None, None, None
    # 优先榫槽 fillet（局部齿根/齿面圆角，删除/修改不影响盘体主实体）；无则盘体
    def _prefer(n):
        return 0 if not _is_disc_component(ir, n.get("component")) else 1
    fns_sorted = sorted(fns, key=_prefer)
    target = fns_sorted[0]
    nid = target.get("id")
    if op == "del":
        role = _slot_fillet_class(ir, target)
        # 前驱 ref（fillet 的 input，通常是 close_profile/add_polyline 的 profile 输出）
        pred_refs = [copy.deepcopy(i) for i in (target.get("inputs") or [])
                     if i.get("node")]
        # 下游引用被删 fillet 输出的节点：重连到前驱 ref（保持链不断）
        for n in ir.get("nodes", []):
            if n.get("id") == nid:
                continue
            ins = n.get("inputs") or []
            for i, inp in enumerate(ins):
                if inp.get("node") == nid:
                    if pred_refs:
                        ins[i] = copy.deepcopy(pred_refs[0])
                    else:
                        ins.pop(i)
            if ins:
                n["inputs"] = ins
        ir["nodes"] = [n for n in ir["nodes"] if n.get("id") != nid]
        label = _fillet_label(ir, target)
        return ir, f"删除{label}圆角（{nid}）。", {"op": "del", "node": nid, "role": role}
    if op == "replace":
        r = target.get("params", {}).get("radius_mm")
        if not isinstance(r, (int, float)):
            return None, None, None
        new_r = round(float(r) * 0.5, 3)
        target["params"]["radius_mm"] = new_r
        label = _fillet_label(ir, target)
        return ir, f"将{label}圆角半径从 {r} 调整为 {new_r}mm。", \
            {"op": "replace", "node": nid, "radius_from": r, "radius_to": new_r}
    if op == "add":
        # 复制一个 fillet 到镜像对称顶点（同一轮廓另一侧），半径稍小（局部修饰）
        ai = target.get("params", {}).get("at_vertex_index")
        idxs = ai if isinstance(ai, list) else ([ai] if isinstance(ai, int) else [])
        if len(idxs) != 1 or not isinstance(idxs[0], int):
            return None, None, None
        # 按组件类型取轮廓点数（盘体 add_polyline vs 榫槽轮廓），保证镜像顶点在合法索引内
        if _is_disc_component(ir, target.get("component")):
            disc_poly = next((n for n in ir.get("nodes", [])
                              if n.get("op") == "add_polyline"
                              and n.get("component") == target.get("component")), None)
            pts = (disc_poly or {}).get("params", {}).get("points")
            if not isinstance(pts, list) or len(pts) < 2:
                return None, None, None
            n_total = len(pts)
        else:
            prof = _slot_profile(ir)
            if not prof:
                return None, None, None
            n_total = len(prof)
        n_upper = n_total // 2
        mirror = 2 * n_upper - 1 - idxs[0]
        if mirror == idxs[0] or mirror < 0 or mirror >= n_total:
            return None, None, None
        if any(n.get("params", {}).get("at_vertex_index") == mirror
               for n in fns):
            return None, None, None  # 该顶点已圆角
        new_node = copy.deepcopy(target)
        new_node["id"] = f"{nid}_mirror"
        new_node["params"]["at_vertex_index"] = mirror
        new_node["params"]["radius_mm"] = round((target.get("params", {}).get("radius_mm") or 1.0) * 0.8, 3)
        ir["nodes"].append(new_node)
        return ir, f"在对称位置添加半径为 {new_node['params']['radius_mm']}mm 的{_fillet_label(ir, target)}圆角。", \
            {"op": "add", "node": new_node["id"], "at_vertex_index": mirror,
             "radius": new_node["params"]["radius_mm"]}
    return None, None, None


def _rebuild_from_ir(tag: str, raw: dict) -> dict:
    """写自定义 IR 到 REGEN_WS 并重建 STEP（复用 regenerate_model 的执行链）。"""
    from seekflow_engineering_tools.generative_cad.pipeline.run import run_gcad_core_from_files
    tag_dir = REGEN_WS / tag
    tag_dir.mkdir(parents=True, exist_ok=True)
    (tag_dir / "raw_fixed.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    out_step = tag_dir / "output.step"
    meta_path = tag_dir / "output.metadata.json"
    try:
        res = run_gcad_core_from_files(tag_dir / "raw_fixed.json", out_step, meta_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"重建执行异常: {exc}", "new_base_dir": str(tag_dir)}
    if not res.ok or not out_step.exists():
        return {"ok": False, "reason": getattr(res, "error", "重建失败"),
                "new_base_dir": str(tag_dir)}
    import cadquery as cq
    try:
        obj = cq.importers.importStep(str(out_step))
        sol = obj.solids().vals()
        vol = sum(s.Volume() for s in sol)
        checks = {"solid_count": len(sol), "volume_mm3": round(vol, 3),
                  "valid_solid": len(sol) == 1 and vol > 0}
    except Exception as exc:  # noqa: BLE001
        checks = {"error": str(exc)}
    return {"ok": True, "new_base_dir": str(tag_dir), "checks": checks}


def _run_feature_one(tid: str, op: str) -> dict | None:
    """特征增删/替换 Edit 样本：改 IR → 重建 → before/after。"""
    base = OUTPUT / tid
    raw_path = base / "raw_fixed.json"
    if not raw_path.exists():
        return None
    ir = json.loads(raw_path.read_text(encoding="utf-8"))
    new_ir, instruction, changes = _apply_feature_op(ir, op)
    if new_ir is None:
        print(f"- {tid}  SKIP  特征 op={op} 不可用（无 fillet/无法镜像）")
        return None
    inh = _inherit(tid)
    before = run_enrich._measure_all(str(base))
    tag = f"{tid}_feat_{op}"
    res = _rebuild_from_ir(tag, new_ir)
    after = run_enrich._measure_all(res.get("new_base_dir") or str(base)) if res.get("ok") else {}
    ok = bool(res.get("ok") and res.get("checks", {}).get("valid_solid"))
    sample_id = f"{tid}_feat_{op}"
    sample = {
        "task_type": "edit", "sample_id": sample_id, "source_task_id": tid,
        "design_id": inh["design_id"], "model_id": inh["model_id"],
        "edit_mode": "feature", "feature_op": changes, "instruction": instruction,
        "param_updates": [], "before": before, "after": after,
        "delta": _delta(before, after),
        "constraint_checks": {"before_ok": True, "after_ok": ok,
                              "constraint_kept": ok, "keep_constraint": False},
        "new_base_dir": res.get("new_base_dir"), "checks": res.get("checks"),
        "validated_ok": ok, "error": None if ok else res.get("reason"),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    DATASETS.mkdir(parents=True, exist_ok=True)
    (DATASETS / f"{sample_id}.json").write_text(
        json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    return sample


def _delta(before: dict, after: dict) -> dict:
    d = {}
    for k in ("outer_diameter_mm", "outer_radius_mm", "axial_thickness_mm",
              "count", "distribution_radius_mm", "circumferential_pitch_mm",
              "slot_depth_mm", "throat_half_width_mm"):
        b, a = before.get(k), after.get(k)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            d[k] = round(a - b, 4)
    return d


def run_one(tid: str, param_specs=None, keep_constraint: bool = False) -> dict | None:
    """param_specs: list[(param_key, new_value or None)]；None → 自动选 1 个可用参数。
    keep_constraint: P1-4 约束保持联动（槽数+分布半径，节距保持）。"""
    base = OUTPUT / tid
    raw_path = base / "raw_fixed.json"
    if not raw_path.exists():
        return None
    ir = json.loads(raw_path.read_text(encoding="utf-8"))
    if keep_constraint:
        param_specs = _constraint_keeping_updates(ir)
    elif param_specs is None:
        reg, cur = _pick_param(ir)
        param_specs = [(reg["param"], None)] if reg else []
    updates, instr_parts = [], []
    for pk, nv in param_specs:
        reg = next((r for r in PARAM_REGISTRY if r["param"] == pk), None)
        if reg is None or not _resolve_param_nodes(ir, pk):
            continue
        cur = _current_value(ir, reg)
        new = nv if nv is not None else _new_value(reg, cur)
        if new is None:
            continue
        updates.append({"param_key": pk, "new_value": new})
        instr_parts.append(f"将{reg['label']}从 {cur} 调整为 {new}{reg['unit']}")
    if not updates:
        print(f"- {tid}  SKIP  无可用参数")
        return None
    inh = _inherit(tid)
    instruction = "；".join(instr_parts) + "。"

    before = run_enrich._measure_all(str(base))
    res = regenerate_model({"base_dir": str(base), "param_updates": updates})
    if not res.get("ok"):
        print(f"- {tid}  FAIL  {res.get('reason')}")
        return None
    after = run_enrich._measure_all(res["new_base_dir"])
    cons_b, cons_a = _constraint_check(str(base)), _constraint_check(res["new_base_dir"])
    sample_id = f"{tid}_" + "_".join(f"{u['param_key']}{u['new_value']}" for u in updates)
    sample = {
        "task_type": "edit", "sample_id": sample_id, "source_task_id": tid,
        "design_id": inh["design_id"], "model_id": inh["model_id"],
        "instruction": instruction,
        "param_updates": res.get("param_changes", []),
        "before": before, "after": after, "delta": _delta(before, after),
        "constraint_checks": {
            "before_ok": bool(cons_b and cons_b.get("ok")),
            "after_ok": bool(cons_a and cons_a.get("ok")),
            "constraint_kept": bool(cons_a and cons_a.get("ok")),
            "keep_constraint": keep_constraint,
        },
        "new_base_dir": res.get("new_base_dir"), "checks": res.get("checks"),
        "validated_ok": bool(res.get("ok") and res.get("checks", {}).get("valid_solid")),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    DATASETS.mkdir(parents=True, exist_ok=True)
    (DATASETS / f"{sample_id}.json").write_text(
        json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    return sample


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Edit 任务样本构造器（改参重生成）")
    ap.add_argument("--only", default=None, help="只处理指定 task_id")
    ap.add_argument("--limit", type=int, default=None, help="最多处理前 N 个任务")
    ap.add_argument("--params", default=None,
                    help='耦合参数 "slot_count:48,root_fillet:1.5"（逗号 k:v，缺 v 则 cur×0.6）')
    ap.add_argument("--keep-constraint", action="store_true",
                    help="P1-4 约束保持联动：槽数×1.25 + 分布半径联动保持周向节距")
    ap.add_argument("--feature", default=None, choices=["del", "add", "replace"],
                    help="论文第 4 类：删除/添加/替换局部特征（fillet_sketch）")
    args = ap.parse_args(argv)

    param_specs = None
    if args.params:
        param_specs = []
        for item in args.params.split(","):
            item = item.strip()
            if not item:
                continue
            if ":" in item:
                k, v = item.split(":", 1)
                param_specs.append((k.strip(), float(v)))
            else:
                param_specs.append((item, None))

    if args.only:
        tasks = [args.only]
    else:
        tasks = sorted(p.name for p in OUTPUT.iterdir()
                       if p.is_dir() and (p / "raw_fixed.json").exists())
    if args.limit:
        tasks = tasks[:args.limit]
    if not tasks:
        print("没有任务目录")
        return 1

    done = 0
    for tid in tasks:
        try:
            if args.feature:
                s = _run_feature_one(tid, args.feature)
            else:
                s = run_one(tid, param_specs, keep_constraint=args.keep_constraint)
            if s:
                done += 1
                mode = s.get("edit_mode", "param")
                print(f"- {tid}  OK  [{mode}] {s['instruction'][:60]}  "
                      f"validated={s['validated_ok']}")
        except Exception as exc:  # noqa: BLE001
            print(f"- {tid}  FAIL  {exc}")
    print(f"DONE  {done} edit samples -> {DATASETS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
