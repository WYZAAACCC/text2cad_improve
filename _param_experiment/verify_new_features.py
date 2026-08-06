"""新模板特征执行验证：groove 减重结构 + complex_rim 圆弧盘体轮廓。

复用 run_batch._run_one（main._run_pipeline 全链：validation/repair/runtime/MCP 门）。
写 verify_* 任务目录（.gitignore 已排除）。不碰主流程/src。

用法:
  .conda/python.exe _param_experiment/verify_new_features.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

import param_templates as pt  # noqa: E402
import run_batch  # noqa: E402

_BASE_GROOVE_TEXT = ("生成一个高压涡轮盘参考几何：轮毂-腹板-轮缘盘体，带环槽与减重结构。"
                     "外径500mm，中心孔直径120mm，轴向最大厚度76mm，轮缘内侧1道环槽，"
                     "环槽槽宽12mm，环槽槽深8mm。")


def _cand(tid: str, cat: str, extra: dict, text: str) -> dict:
    params = {"category": cat, "od_mm": 500, "bore_mm": 120, "thick_mm": 76,
              "hub_mm": 38, "rim_mm": 30}
    params.update(extra)
    return {"task_id": tid, "category": cat, "params": params, "text": text}


def _run(cand: dict) -> dict:
    out_dir = run_batch.OUTPUT / cand["task_id"]
    try:
        status = run_batch._run_one(cand, use_template=True)
    except Exception as exc:  # noqa: BLE001
        return {"tid": cand["task_id"], "status": "exception", "error": str(exc)[:300]}
    info = {"tid": cand["task_id"], "status": status}
    vf = out_dir / "validation_report.json"
    if vf.exists():
        v = json.loads(vf.read_text(encoding="utf-8"))
        info["validation_ok"] = v.get("ok")
        info["issues"] = [i.get("issue") for i in (v.get("issues") or [])][:5]
    info["step"] = (out_dir / "output.step").exists()
    info["raw_fixed"] = (out_dir / "raw_fixed.json").exists()
    return info


def main() -> int:
    cases = [
        # ── groove 减重特征：逐特征独立 + 全组合 ──
        _cand("verify_g_lh", "groove", {"lh_holes": 12, "lh_pcd_mm": 175, "lh_hdia_mm": 16},
              _BASE_GROOVE_TEXT + "腹板处12个减重孔，孔径16mm，分布半径175mm。参考几何，非适航件。"),
        _cand("verify_g_cl", "groove", {"cl_holes": 24, "cl_pcd_mm": 225, "cl_hdia_mm": 6},
              _BASE_GROOVE_TEXT + "腹板处24个冷却孔，孔径6mm，分布半径225mm。参考几何，非适航件。"),
        _cand("verify_g_rs", "groove", {"rs_count": 60, "rs_depth_mm": 10, "rs_half_width_mm": 3.0},
              _BASE_GROOVE_TEXT + "轮缘外表面60个径向局部切槽，槽深10mm，槽宽6mm。参考几何，非适航件。"),
        _cand("verify_g_cav", "groove", {"cavity_width_mm": 40, "cavity_depth_mm": 4.0},
              _BASE_GROOVE_TEXT + "腹板处环形减重腔，腔宽40mm，腔深4mm。参考几何，非适航件。"),
        _cand("verify_g_all", "groove",
              {"grooves": 1, "gw_mm": 12, "gd_mm": 8,
               "lh_holes": 12, "lh_pcd_mm": 175, "lh_hdia_mm": 16,
               "cl_holes": 24, "cl_pcd_mm": 225, "cl_hdia_mm": 6, "cl_pcd2_mm": 240,
               "rs_count": 60, "rs_depth_mm": 10, "rs_half_width_mm": 3.0,
               "cavity_width_mm": 40, "cavity_depth_mm": 4.0},
              _BASE_GROOVE_TEXT + "腹板处12个减重孔孔径16mm分布半径175mm，24个冷却孔孔径6mm分布半径225mm第二排240mm，"
                                 "轮缘外表面60个径向局部切槽槽深10mm槽宽6mm，腹板环形减重腔腔宽40mm腔深4mm。参考几何，非适航件。"),
        # ── complex_rim 圆弧盘体：多圆弧半径变体 ──
        _cand("verify_cx_arc20", "complex_rim",
              {"slots": 60, "teeth": 3, "R_mm": 225, "depth_mm": 32,
               "throat_half_width_mm": 4.0, "fr_mm": 1.0, "rim_arc_radius_mm": 20.0},
              "生成一个高压涡轮盘参考几何：轮毂-腹板-轮缘盘体，带厚轮缘与枞树形榫槽，"
              "曲线过渡轮缘。外径500mm，中心孔直径120mm，轴向最大厚度76mm，"
              "轮毂半厚38mm，轮缘半厚30mm，轮缘上60个3齿枞树形榫槽，分布半径225mm，"
              "槽深32mm，喉部半宽4mm，齿根圆角1mm。参考几何，非适航件。"),
        _cand("verify_cx_arc12", "complex_rim",
              {"slots": 60, "teeth": 3, "R_mm": 225, "depth_mm": 32,
               "throat_half_width_mm": 4.0, "fr_mm": 1.0, "rim_arc_radius_mm": 12.0},
              "生成一个高压涡轮盘参考几何：复杂轮缘过渡盘。外径500mm，中心孔直径120mm，"
              "轴向最大厚度76mm，轮毂半厚38mm，轮缘半厚30mm，轮缘上60个3齿枞树形榫槽，"
              "分布半径225mm，槽深32mm，喉部半宽4mm，齿根圆角1mm。参考几何，非适航件。"),
        _cand("verify_cx_arc30", "complex_rim",
              {"slots": 84, "teeth": 3, "R_mm": 250, "depth_mm": 38,
               "throat_half_width_mm": 5.0, "fr_mm": 2.0, "rim_arc_radius_mm": 30.0},
              "生成一个高压涡轮盘参考几何：复杂轮缘过渡盘。外径640mm，中心孔直径150mm，"
              "轴向最大厚度90mm，轮毂半厚45mm，轮缘半厚38mm，轮缘上84个3齿枞树形榫槽，"
              "分布半径250mm，槽深38mm，喉部半宽5mm，齿根圆角2mm。参考几何，非适航件。"),
    ]
    results = []
    for c in cases:
        r = _run(c)
        results.append(r)
        print(f"[{r['tid']}] status={r.get('status')} validation={r.get('validation_ok')} "
              f"step={r.get('step')} raw_fixed={r.get('raw_fixed')} "
              f"issues={r.get('issues')} err={r.get('error', '')}")
    passed = [r for r in results if r.get("status") == "completed" and r.get("validation_ok")]
    print(f"\n通过 {len(passed)}/{len(results)}")
    return 0 if len(passed) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
