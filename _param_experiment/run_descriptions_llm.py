"""LLM 生成三描述（Gen 任务输入，用户流程第 4 步）。

对给定设计族参数组合，用 LLM 生成三条不同风格的自然语言建模需求：
  - cn_param   中文简洁参数化指令
  - cn_semantic 中文工程语义描述
  - en_mixed   英文/中英混合参数说明
并用 extract_requirements 验证描述包含的关键参数与输入参数一致（不一致重生成，最多 2 次）。

独立于主流程/src；LLM 调用复用 DeepSeekToolCaller（call_strict_tool + 宽松 schema）。

用法:
  .conda/python.exe _param_experiment/run_descriptions_llm.py --params '{"od_mm":500,"bore_mm":120,"slots":60,"teeth":2}'
  .conda/python.exe _param_experiment/run_descriptions_llm.py --from-candidates --limit 2 --family D15
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller  # noqa: E402
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig  # noqa: E402
from validate_req_params import extract_requirements  # noqa: E402

_DESC_SCHEMA = {
    "type": "object",
    "properties": {
        "cn_param": {"type": "string", "description": "中文简洁参数化指令，罗列全部关键尺寸与特征参数"},
        "cn_semantic": {"type": "string", "description": "中文工程语义描述，工程化措辞面向设计意图"},
        "en_mixed": {"type": "string", "description": "English or mixed English-Chinese parameter description"},
    },
    "required": ["cn_param", "cn_semantic", "en_mixed"],
}

# 模板参数键 → extract_requirements 键 + 容差
_PARAM_TOL = {
    "od_mm": ("outer_diameter_mm", 5.0), "bore_mm": ("bore_diameter_mm", 5.0),
    "thick_mm": ("axial_thickness_mm", 3.0), "hub_mm": ("hub_half_mm", 3.0),
    "rim_mm": ("rim_half_mm", 3.0), "slots": ("slots", 0), "teeth": ("teeth_count", 0),
    "depth_mm": ("slot_depth_mm", 2.0), "throat_half_width_mm": ("throat_half_width_mm", 0.5),
    "fr_mm": ("root_fillet_mm", 0.3), "holes": ("holes", 0), "pcd_mm": ("pcd_mm", 2.0),
    "hdia_mm": ("hdia_mm", 0.5), "grooves": ("grooves", 0), "gw_mm": ("gw_mm", 0.5),
    "gd_mm": ("gd_mm", 0.5), "R_mm": ("R_mm", 2.0),
    "lh_holes": ("lh_holes", 0), "lh_pcd_mm": ("lh_pcd_mm", 2.0), "lh_hdia_mm": ("lh_hdia_mm", 0.5),
    "cl_holes": ("cl_holes", 0), "cl_pcd_mm": ("cl_pcd_mm", 2.0), "cl_hdia_mm": ("cl_hdia_mm", 0.5),
    "cl_pcd2_mm": ("cl_pcd2_mm", 2.0),
    "rs_count": ("rs_count", 0), "rs_depth_mm": ("rs_depth_mm", 1.0),
    "cavity_width_mm": ("cavity_width_mm", 1.0), "cavity_depth_mm": ("cavity_depth_mm", 0.5),
    "rim_arc_radius_mm": ("rim_arc_radius_mm", 1.0),
}

_DISK_CN = {"basic": "基础轮毂-腹板-轮缘盘", "hole": "带周向孔阵列的轮毂-腹板-轮缘盘",
            "groove": "带环槽的轮毂-腹板-轮缘盘", "slot": "带枞树形榫槽的轮毂-腹板-轮缘盘",
            "coupled": "带枞树形榫槽、周向孔阵列与环槽的耦合涡轮盘",
            "complex_rim": "带厚轮缘与枞树形榫槽的复杂轮缘涡轮盘"}


def _key():
    for cand in (ROOT / "_archive" / "apikey.txt", Path(r"E:\auto_detection_process\_archive\apikey.txt")):
        if cand.exists():
            os.environ["DEEPSEEK_API_KEY"] = cand.read_text(encoding="utf-8").strip()
            return
    raise SystemExit("未找到 apikey.txt")


def _param_summary(params: dict) -> str:
    p = [f"外径{params.get('od_mm')}mm，中心孔直径{params.get('bore_mm')}mm，"
         f"轴向最大厚度{params.get('thick_mm')}mm，轮毂半厚{params.get('hub_mm')}mm，"
         f"轮缘半厚{params.get('rim_mm')}mm"]
    if params.get("slots"):
        p.append(f"轮缘上{params['slots']}个{params['teeth']}齿枞树形榫槽，槽深{params['depth_mm']}mm，"
                 f"喉部半宽{params['throat_half_width_mm']}mm，齿根圆角{params['fr_mm']}mm")
    if params.get("holes"):
        p.append(f"周向均布{params['holes']}个安装孔，孔径{params['hdia_mm']}mm，分布半径{params['pcd_mm']}mm")
    if params.get("grooves"):
        p.append(f"轮缘内侧{params['grooves']}道环槽，环槽槽宽{params['gw_mm']}mm，环槽槽深{params['gd_mm']}mm")
    if params.get("lh_holes"):
        p.append(f"腹板{params['lh_holes']}个减重孔，孔径{params['lh_hdia_mm']}mm，分布半径{params['lh_pcd_mm']}mm")
    if params.get("cl_holes"):
        p.append(f"腹板{params['cl_holes']}个冷却孔，孔径{params['cl_hdia_mm']}mm，分布半径{params['cl_pcd_mm']}mm")
    if params.get("rs_count"):
        p.append(f"轮缘外表面{params['rs_count']}个径向切槽，切槽深度{params['rs_depth_mm']}mm")
    if params.get("cavity_width_mm"):
        p.append(f"腹板环形减重腔，腔宽{params['cavity_width_mm']}mm，腔深{params['cavity_depth_mm']}mm")
    if params.get("rim_arc_radius_mm"):
        p.append(f"轮缘圆弧曲线过渡半径{params['rim_arc_radius_mm']}mm")
    return "，".join(p)


def _system(cat: str, params: dict) -> str:
    return (f"你是航空发动机涡轮盘建模需求编写专家。根据给定盘型与参数，编写三条不同风格的自然语言建模需求。\n"
            f"1. cn_param：中文简洁参数化指令（直接罗列关键尺寸与特征参数）\n"
            f"2. cn_semantic：中文工程语义描述（工程化措辞，面向设计意图）\n"
            f"3. en_mixed：英文或中英混合参数说明\n"
            f"必须包含盘型与全部关键参数。这是参考几何、非适航件。\n"
            f"盘型：{_DISK_CN.get(cat, cat)}\n"
            f"参考参数：{_param_summary(params)}")


def _validate(desc: str, params: dict, style: str = "cn") -> list:
    """描述中可提取参数 vs 输入参数一致性。返回不一致项。

    cn 风格用 extract_requirements（中文正则，含 Φ 容忍 + 榫槽分布半径）；
    en_mixed 是英文，中文正则提取为空 → 用"关键参数值出现在文本"的宽松值级校验，
    避免 en_mixed 永远 validated=True 的假信号。
    """
    if style == "en":
        bad = []
        flat = desc.replace(",", " ").replace("，", " ").replace("Φ", "")
        for k, expected in params.items():
            if k not in _PARAM_TOL or expected is None:
                continue
            needle = str(int(expected)) if isinstance(expected, float) and expected == int(expected) \
                else str(expected)
            if needle not in flat:
                bad.append(f"{k}:期望{expected}未出现在英文描述")
        return bad
    req = extract_requirements(desc)
    bad = []
    for k, expected in params.items():
        if k not in _PARAM_TOL or expected is None:
            continue
        rkey, tol = _PARAM_TOL[k]
        if rkey not in req:
            continue  # 描述未明确给出该参数 → 宽容（允许省略）
        got = req[rkey]
        if isinstance(got, int) and isinstance(expected, int):
            if got != expected:
                bad.append(f"{rkey}:期望{expected}实际{got}")
        elif abs(got - expected) > tol:
            bad.append(f"{rkey}:期望{expected}实际{got}")
    return bad


def gen_descriptions(cat: str, params: dict, caller=None, config=None) -> dict:
    """LLM 生成 3 描述 + 参数一致性验证（重生成最多 2 次）。"""
    if caller is None:
        _key()
        caller = DeepSeekToolCaller()
        config = LlmModelConfig(model="deepseek-chat", use_strict_tools=True)
    last = None
    for _attempt in range(3):
        try:
            tc = caller.call_strict_tool(
                messages=[{"role": "system", "content": _system(cat, params)},
                          {"role": "user", "content": "请编写上述三条建模需求。"}],
                tool_name="emit_descriptions", tool_description="生成 3 条自然语言建模需求",
                tool_schema=_DESC_SCHEMA, model_config=config)
            last = tc.arguments
            bad = _validate(last.get("cn_param", ""), params, "cn") \
                + _validate(last.get("cn_semantic", ""), params, "cn") \
                + _validate(last.get("en_mixed", ""), params, "en")
            if not bad:
                return {"styles": last, "validated": True, "issues": []}
        except Exception as exc:  # noqa: BLE001
            last = {"error": str(exc)[:200]}
    return {"styles": last, "validated": False, "issues": bad if 'bad' in dir() else ["重试耗尽"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LLM 生成三描述")
    ap.add_argument("--params", default=None, help="参数向量 JSON")
    ap.add_argument("--from-candidates", action="store_true", help="从 candidates.json 批量")
    ap.add_argument("--family", default=None, help="--from-candidates 时只处理指定族")
    ap.add_argument("--limit", type=int, default=None, help="最多处理 N 个")
    args = ap.parse_args(argv)

    _key()
    caller = DeepSeekToolCaller()
    config = LlmModelConfig(model="deepseek-chat", use_strict_tools=True)

    items = []
    if args.params:
        items = [{"category": "slot", "params": json.loads(args.params)}]
    elif args.from_candidates:
        cand = json.loads((_HERE / "output" / "datasets" / "candidates.json").read_text(encoding="utf-8"))
        cands = cand.get("candidates", [])
        if args.family:
            cands = [c for c in cands if c.get("family") == args.family]
        if args.limit:
            cands = cands[: args.limit]
        items = [{"category": c.get("category"), "params": c.get("params", {})} for c in cands]
    else:
        print("需要 --params 或 --from-candidates")
        return 1

    out = []
    for i, it in enumerate(items, 1):
        print(f"[{i}/{len(items)}] 生成三描述 ...", end=" ", flush=True)
        r = gen_descriptions(it["category"], it["params"], caller, config)
        ok = r.get("validated")
        print("OK" if ok else f"未通过: {r.get('issues', [])[:2]}")
        out.append({"category": it["category"], "params": it["params"], **r})

    _HERE.joinpath("output", "datasets").mkdir(parents=True, exist_ok=True)
    dst = _HERE / "output" / "datasets" / "descriptions_llm.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
