import os
import sys
import json
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process")
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server")
from openai import OpenAI
import agentic_l2

text = "生成一个锥形腹板高压涡轮盘参考几何，外径520mm，中心孔直径120mm，轴向最大厚度76mm，轮毂半厚38mm，轮缘半厚30mm。参考几何，非适航件。"
user = text + agentic_l2._append_parametric_block(text)
client = OpenAI(api_key=os.environ["QWEN_API_KEY"], base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", timeout=90)
tools = []
for name, spec in agentic_l2._GENERIC_CALC_TOOLS.items():
    tools.append({"type": "function", "function": {"name": name, "description": spec["description"], "strict": False, "parameters": spec["schema"]}})
tools.append({"type": "function", "function": {"name": "emit_design_plan", "description": "输出最终 AgentDesignPlan", "strict": False, "parameters": agentic_l2.AGENT_A_TOOL_SCHEMA}})
messages = [{"role": "system", "content": agentic_l2.AGENT_A_SYSTEM}, {"role": "user", "content": user}]
for rnd in range(8):
    resp = client.chat.completions.create(model="qwen3.7-plus", messages=messages, tools=tools, tool_choice="required", max_tokens=8192, temperature=0.3, seed=0, extra_body={})
    m = resp.choices[0].message
    if not m.tool_calls:
        print("round", rnd, "NO TOOL CALL", (m.content or "")[:100]); break
    call = m.tool_calls[0]
    raw = call.function.arguments
    print("round", rnd, "tool:", call.function.name, "raw_len:", len(raw))
    try:
        args = json.loads(raw)
    except Exception as exc:
        print("  JSON ERR:", str(exc)[:100]); break
    if call.function.name == "emit_design_plan":
        issues = agentic_l2._validate_agent_a_plan(args, text)
        print("  plan validation issues:", len(issues))
        for i in issues[:12]:
            print("   -", i)
        break
    # tool call
    result = agentic_l2._GENERIC_CALC_TOOLS[call.function.name]["handler"](args)
    messages.append({"role": "assistant", "tool_calls": [{"id": call.id, "type": "function", "function": {"name": call.function.name, "arguments": raw}}]})
    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
    messages.append({"role": "user", "content": "计算完成。请立即调用 emit_design_plan 输出最终 plan。"})

