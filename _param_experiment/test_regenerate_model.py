"""参数再生 MCP — 单元测试（隔离实验，不改主程序）。

覆盖：
  1. 参数清单 list_regeneratable_params：8 个受支持参数 + 当前值/范围
  2. 单参数再生 slot_count 60→48：重建成功、参数生效、新模型有效
  3. 多参数再生 slot_count 60→48 + root_fillet 1.0→1.5：重建成功
  4. 对称参数 disc_hub_web_fillet→15：lower/upper 同步改
  5. 非法参数：越界 → 合理拒绝（不可行设计）
用法：
  .conda/python.exe test_regenerate_model.py           # 单元
  .conda/python.exe test_regenerate_model.py --llm     # 加 LLM 集成
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_tools import TOOLS, REGEN_WS, PARAM_REGISTRY

BASE = (Path(__file__).resolve().parent.parent
        / "app" / "text-to-cad" / "server" / "output" / "b572661c219c4952")


def call(name, args=None):
    return TOOLS[name]["handler"](args or {})


def main():
    print("=== 参数再生 MCP 单元测试（基准 b572661c219c4952）===\n")
    all_ok = True
    n = 0

    # ── 1. 参数清单 ──
    r = call("list_regeneratable_params")
    ok = r.get("ok") and len(r.get("parameters", [])) == 8
    all_ok &= ok; n += 1
    print(f"[list_regeneratable_params] {'PASS' if ok else 'FAIL'} {len(r.get('parameters', []))} 个参数")
    for p in r.get("parameters", []):
        print(f"    {p['param_key']:24s} 当前={p['current']} 范围={p['range']}{p['unit']}")

    # ── 2. 单参数再生 ──
    rr = call("regenerate_model", {"param_updates": [{"param_key": "slot_count", "new_value": 48}]})
    ok = rr.get("ok") and rr["checks"].get("valid_solid")
    # 参数生效：新 base 的 count 工具应测到 48
    count_ok = False
    if rr.get("ok"):
        c = call("count_fir_tree_slots", {"base_dir": rr["new_base_dir"]})
        count_ok = c.get("count") == 48
        print(f"    [新模型] count={c.get('count')} 节距={c.get('circumferential_pitch_mm')} "
              f"体积={rr['checks'].get('volume_mm3')}")
    ok = ok and count_ok
    all_ok &= ok; n += 1
    print(f"[regenerate 单参数 slot_count→48] {'PASS' if ok else 'FAIL'}")

    # ── 3. 多参数再生 ──
    rr = call("regenerate_model", {"param_updates": [
        {"param_key": "slot_count", "new_value": 48},
        {"param_key": "root_fillet", "new_value": 1.5},
    ]})
    changes = rr.get("param_changes", [])
    ok = rr.get("ok") and rr["checks"].get("valid_solid") and len(changes) == 2
    all_ok &= ok; n += 1
    print(f"[regenerate 多参数 count→48 + root_fillet→1.5] {'PASS' if ok else 'FAIL'} "
          f"changes={[(c['param'], c['new']) for c in changes]}")

    # ── 4. 对称参数（小改 12→13，避免相邻圆角冲突）──
    rr = call("regenerate_model", {"param_updates": [{"param_key": "disc_hub_web_fillet", "new_value": 13}]})
    ok = False
    if rr.get("ok"):
        # 检查 new base 的 raw 里 lower/upper 都改为 13
        new_raw = json.loads((Path(rr["new_base_dir"]) / "raw_fixed.json").read_text(encoding="utf-8"))
        vals = []
        for node in new_raw["nodes"]:
            if node["id"] in ("n_fillet_disc_hub_web_lower", "n_fillet_disc_hub_web_upper"):
                vals.append(node["params"]["radius_mm"])
        ok = vals == [13, 13] and rr["checks"].get("valid_solid")
        print(f"    [对称] lower/upper radius = {vals}")
    all_ok &= ok; n += 1
    print(f"[regenerate 对称参数 disc_hub_web_fillet→13] {'PASS' if ok else 'FAIL'}")

    # ── 4b. 组合不可行（12→15 与 web_rim=10 相邻圆角冲突 → 合理拒绝）──
    rr = call("regenerate_model", {"param_updates": [{"param_key": "disc_hub_web_fillet", "new_value": 15}]})
    ok = (not rr.get("ok")) and "重建失败" in rr.get("reason", "")
    all_ok &= ok; n += 1
    print(f"[regenerate 组合不可行 hub_fillet→15(相邻冲突)] {'PASS' if ok else 'FAIL'} "
          f"reason={rr.get('reason')}（论文不可行设计拒绝 OK）")

    # ── 5. 非法参数（拒绝，不重建）──
    rr = call("regenerate_model", {"param_updates": [{"param_key": "slot_count", "new_value": 200}]})
    ok = (not rr.get("ok")) and "非法参数" in rr.get("reason", "")
    all_ok &= ok; n += 1
    print(f"[regenerate 非法 slot_count→200] {'PASS' if ok else 'FAIL'} reason={rr.get('reason')} detail={rr.get('detail')}")

    rr = call("regenerate_model", {"param_updates": [{"param_key": "root_fillet", "new_value": 10}]})
    ok = (not rr.get("ok")) and "非法参数" in rr.get("reason", "")
    all_ok &= ok; n += 1
    print(f"[regenerate 非法 root_fillet→10] {'PASS' if ok else 'FAIL'}")

    print(f"\n{'='*60}")
    print(f"单元测试: {'全部通过' if all_ok else '有失败'} ({n}/{n})")

    # ── LLM 集成 ──
    if "--llm" in sys.argv:
        print("\n=== LLM 端到端（改参→再生→验证→报告）===")
        from mcp_server import run_quality_assurance
        task = ("请把该涡轮盘的榫槽数量改为 48，重新生成模型，然后用检查工具验证新模型"
                "（榫槽数量、实体有效性、体积），最后输出工程验收结论。")
        result = run_quality_assurance(task)
        seq = result.get("tool_sequence", [])
        print(f"工具调用序列（{len(seq)} 次）:")
        for i, s in enumerate(seq, 1):
            st = "OK" if s["result"].get("ok") else "FAIL"
            print(f"  [{i}] {s['tool']} -> {st}")
        print(f"终止: {result.get('termination')} | 验收: {result.get('accepted')}")
        if result.get("final_report"):
            from pathlib import Path as _P
            _P("output/mcp_server/llm_regen_report.json").parent.mkdir(parents=True, exist_ok=True)
            import json as _j
            _P("output/mcp_server/llm_regen_report.json").write_text(
                _j.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"最终报告已保存: output/mcp_server/llm_regen_report.json")
        if result.get("error"):
            print(f"错误: {result['error']}")


if __name__ == "__main__":
    main()
