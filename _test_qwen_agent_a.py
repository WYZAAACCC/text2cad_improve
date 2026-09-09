import os
import sys
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process")
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server")
from openai import OpenAI
import agentic_l2

client = OpenAI(api_key=os.environ["QWEN_API_KEY"], base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", timeout=60)
tool = {"type": "function", "function": {"name": "emit_design_plan", "description": "输出最终 AgentDesignPlan", "strict": False, "parameters": agentic_l2.AGENT_A_TOOL_SCHEMA}}
resp = client.chat.completions.create(
    model="qwen3.7-plus",
    messages=[{"role": "user", "content": "生成一个高压涡轮盘参考几何，外径500mm，中心孔直径120mm，轴向最大厚度76mm。参考几何，非适航件。"}],
    tools=[tool], tool_choice="required", max_tokens=2048, temperature=0.3,
)
m = resp.choices[0].message
print("finish:", resp.choices[0].finish_reason, "tool_calls:", bool(m.tool_calls))
if m.tool_calls:
    raw = m.tool_calls[0].function.arguments
    print("raw len:", len(raw))
    print("raw head:", raw[:300])
    print("raw tail:", raw[-200:])
    import json
    try:
        json.loads(raw)
        print("JSON OK")
    except Exception as exc:
        print("JSON ERR:", str(exc)[:120])
else:
    print("content:", (m.content or "")[:200])

