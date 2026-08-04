"""DiskCAD-MCP 服务器 — 多轮 agentic loop（LLM 按工具说明发现并调用）。

对论文"LLM 按工具名称/功能描述/输入 schema 发现并调用外部能力"的行为等价实现：
  - 全部 MCP 工具（mcp_tools.TOOLS）以 OpenAI function schema 注册
  - 附加 finish_quality_check 收尾工具（LLM 收集完证据后调用，输出工程验收报告）
  - 循环：LLM 选工具 → 程序执行 handler → 结果回喂 → 直到 finish / 无工具调用 / 达上限
  - 每轮校验工具名（防幻觉）、args 容错

用法:
  result = run_quality_assurance("检查涡轮盘外径、榫槽数量、齿数、节距剩余材料和 STEP 回读是否合格")
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "integrations" / "engineering_tools" / "src"
sys.path.insert(0, str(SRC))

from openai import OpenAI

from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema

from mcp_tools import TOOLS

MODEL_CONFIG = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")
API_KEY_FILE = ROOT / "_archive" / "apikey.txt"

BASE_DIR = (ROOT / "app" / "text-to-cad" / "server" / "output" / "b572661c219c4952")


def _build_openai_tools() -> list:
    tools = []
    for name, t in TOOLS.items():
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": t["description"],
                "strict": False,
                "parameters": to_deepseek_strict_schema(t["input_schema"]),
            },
        })
    tools.append({
        "type": "function",
        "function": {
            "name": "finish_quality_check",
            "description": "完成全部检查后调用：输出最终工程验收报告（汇总各工具结果 + 结论）。",
            "strict": False,
            "parameters": {
                "type": "object",
                "properties": {
                    "report": {"type": "string",
                               "description": "最终质量报告（含关键测量值、约束判定、验收结论）"},
                    "accepted": {"type": "boolean",
                                 "description": "是否通过工程验收"},
                },
                "required": ["report", "accepted"],
                "additionalProperties": False,
            },
        },
    })
    return tools


def _system_prompt(base_dir) -> str:
    lines = [
        "你是航空发动机涡轮盘 CAD 质量检查工程师。",
        "你可以通过 MCP 工具对生成的 CAD 模型执行独立质量检查（实体健康、尺寸、榫槽、几何约束、STEP 回读等）。",
        f"被检查的模型基准目录：{base_dir}（含 raw_fixed.json = Disk-G-CAD、output.step = STEP 模型）。",
        "",
        "可用工具（名称 + 说明 + 输入 schema）：",
    ]
    for name, t in TOOLS.items():
        schema = json.dumps(t["input_schema"], ensure_ascii=False)
        lines.append(f"  - {name}: {t['description']}")
        lines.append(f"    schema: {schema}")
    lines += [
        "",
        "流程要求：",
        "  1. 根据任务自然语言，选择【合适的工具】逐项检查（一次调用一个工具）",
        "  2. 工具返回结构化结果后，再选择下一个工具或重复需要的检查",
        "  3. 覆盖：实体有效性、关键尺寸、榫槽数量/齿数/节距/剩余材料、STEP 回读",
        "  4. 一旦获得足够证据得出验收结论，【必须】调用 finish_quality_check 输出最终报告",
        "     （含关键测量值、约束判定、验收结论）；不要无意义地重复或堆叠检查工具",
        "  5. 禁止调用工具清单之外的名称；工具参数按 schema 提供（base_dir 可省略，默认基准目录）",
    ]
    return "\n".join(lines)


def run_quality_assurance(task_nl: str, base_dir=None, max_rounds: int = 16) -> dict:
    """执行一次端到端 MCP 质量检查任务。返回工具调用序列 + 最终报告。"""
    base_dir = str(base_dir or BASE_DIR)
    api_key = API_KEY_FILE.read_text(encoding="utf-8").strip()
    os.environ["DEEPSEEK_API_KEY"] = api_key

    client = OpenAI(api_key=api_key, base_url=MODEL_CONFIG.base_url)
    messages: list = [
        {"role": "system", "content": _system_prompt(base_dir)},
        {"role": "user", "content": task_nl},
    ]
    seq: list = []
    tools = _build_openai_tools()

    for _round in range(max_rounds):
        try:
            resp = client.chat.completions.create(
                model=MODEL_CONFIG.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                timeout=MODEL_CONFIG.timeout_s,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except Exception as exc:
            return {"ok": False, "error": f"LLM 调用失败: {exc}", "tool_sequence": seq}

        msg = resp.choices[0].message

        # 无工具调用 = LLM 直接给出最终答复（视为完成）
        if not msg.tool_calls:
            return {"ok": True, "tool_sequence": seq,
                    "final_report": msg.content or "", "accepted": None,
                    "termination": "no_tool_call"}

        # 本轮可能有多个工具调用（DeepSeek auto 模式下逐个执行）
        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            # 收尾工具
            if name == "finish_quality_check":
                return {"ok": True, "tool_sequence": seq,
                        "final_report": args.get("report", ""),
                        "accepted": args.get("accepted"),
                        "termination": "finish_quality_check"}

            # 校验工具名（防幻觉）
            if name not in TOOLS:
                result = {"ok": False, "error": f"未知工具名 {name!r}（请从工具清单中选择）"}
            else:
                try:
                    result = TOOLS[name]["handler"](args)
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}

            seq.append({"tool": name, "args": args, "result": result})

            # 回喂工具结果
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call.id,
                    "type": "function",
                    "function": {"name": name, "arguments": call.function.arguments or "{}"},
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return {"ok": False, "error": "达到最大轮数未收敛", "tool_sequence": seq,
            "final_report": "", "termination": "max_rounds"}


if __name__ == "__main__":
    task = ("请对该涡轮盘执行完整质量检查：实体有效性、外径/中心孔直径/轴向厚度、"
            "榫槽数量、齿数、槽深、齿面角、周向节距与最小剩余材料、槽深与轮缘厚度约束、"
            "STEP 导出-回读体积一致性。汇总结果并给出工程验收结论。")
    result = run_quality_assurance(task)
    print("=== 工具调用序列 ===")
    for i, s in enumerate(result.get("tool_sequence", []), 1):
        print(f"  [{i}] {s['tool']} args={s['args']}")
        print(f"      result.ok={s['result'].get('ok')}")
    print(f"\n=== 终止方式: {result.get('termination')} ===")
    if result.get("final_report"):
        print(f"\n=== 最终报告 ===\n{result['final_report']}")
    if result.get("error"):
        print(f"\n错误: {result['error']}")
