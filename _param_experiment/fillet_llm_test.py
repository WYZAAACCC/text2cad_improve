"""圆角 LLM 指定测试 — 验证 LLM 能否全覆盖"必须圆角的角清单"。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "integrations" / "engineering_tools" / "src"
sys.path.insert(0, str(SRC))

from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema

from fir_tree_parametric import FirTreeParams, generate_profile
from fillet_corners import list_required_corners, llm_schema, verify_coverage

MODEL_CONFIG = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")
API_KEY_FILE = ROOT / "_archive" / "apikey.txt"

ROLE_HINT = {
    "tip_flank_top": "齿顶外斜面端",
    "tip_platform_end": "齿顶平台端",
    "neck": "齿根/颈部",
    "bottom_flare": "槽底外扩角",
    "root": "根部",
}
RADIUS_HINT = {"tip_flank_top": 0.8, "tip_platform_end": 0.8, "neck": 0.5, "bottom_flare": 0.6, "root": 0.6}


def build_prompt(corners: list, teeth_count: int) -> str:
    lines = [f"枞树形榫槽（{teeth_count}齿）轮廓已生成，有 {len(corners)} 个【必须圆角的角】。", ""]
    lines.append("必须圆角的角清单（一个都不能漏）：")
    for c in corners:
        lines.append(f"  - role={c['role']:16s} tooth_index={c['tooth_index']:3d}  ({ROLE_HINT[c['role']]})")
    lines.append("")
    lines.append("请为【清单中的每一个角】输出一条 {role, tooth_index, radius_mm}。")
    lines.append("建议半径：齿顶(role 含 tip)≈0.8，齿根(neck)≈0.5，底部(bottom_flare/root)≈0.6。")
    lines.append("严禁遗漏任何一个角，也不要输出清单之外的角。")
    return "\n".join(lines)


def call_llm(prompt: str) -> list:
    caller = DeepSeekToolCaller()
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": "请输出 fillets。"}]
    r = caller.call_strict_tool(
        messages=messages,
        tool_name="emit_fillets",
        tool_description="Emit fillet specs for required corners",
        tool_schema=to_deepseek_strict_schema(llm_schema()),
        model_config=MODEL_CONFIG,
    )
    return list(r.arguments.get("fillets", []))


def main():
    key = API_KEY_FILE.read_text(encoding="utf-8").strip()
    os.environ["DEEPSEEK_API_KEY"] = key

    print("=== 圆角 LLM 指定测试 ===\n")
    for n in (2, 3):
        p = FirTreeParams(
            teeth_count=n, slot_depth_mm=26,
            tooth_height_mm=[7 - i * 0.8 for i in range(n)], tooth_thickness_mm=[2] * n,
            top_flank_angle_deg=[66.7] * n, under_flank_angle_deg=[60] * n,
            neck_half_width_mm=[2.6 - i * 0.2 for i in range(n + 1)], neck_platform_mm=2.0,
            bottom_half_width_mm=4.0, bottom_platform_mm=2.0, bottom_flare_angle_deg=60,
        )
        pts = generate_profile(p)
        corners = list_required_corners(pts, n)
        prompt = build_prompt(corners, n)
        try:
            llm = call_llm(prompt)
        except Exception as e:
            print(f"[{n}齿] LLM 调用失败: {e}")
            continue
        ok, missing, extra, dup = verify_coverage(corners, llm)
        print(f"[{n}齿] 必须角={len(corners)}  LLM指定={len(llm)}  覆盖={'PASS' if ok else 'FAIL'}")
        if missing:
            print(f"  MISSING(漏): {missing}")
        if extra:
            print(f"  EXTRA(多): {extra}")
        if dup:
            print(f"  DUP(重复): {dup}")
        # 打印 LLM 指定的半径
        for f in llm:
            print(f"  {f['role']}@{f['tooth_index']} r={f['radius_mm']}")


if __name__ == "__main__":
    main()
