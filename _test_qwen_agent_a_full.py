import os
import sys
import json
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process")
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server")
from openai import OpenAI
import agentic_l2

client = OpenAI(api_key=os.environ["QWEN_API_KEY"], base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", timeout=90)
text = "生成一个高压涡轮盘参考几何，外径500mm，中心孔直径120mm，轴向最大厚度76mm，轮毂半厚38mm，轮缘半厚30mm，保持原有主体结构，仅调整上述参数。参考几何，非适航件。"
user = text + agentic_l2._append_parametric_block(text)
print("user len:", len(user))
tool = {"type": "function", "function": {"name": "emit_design_plan", "description": "输出最终 AgentDesignPlan", "strict": False, "parameters": agentic_l2.AGENT_A_TOOL_SCHEMA}}
resp = client.chat.completions.create(
    model="qwen3.7-plus",
    messages=[{"role": "system", "content": agentic_l2.AGENT_A_SYSTEM}, {"role": "user", "content": user}],
    tools=[tool], tool_choice="required", max_tokens=8192, temperature=0.3,
)
m = resp.choices[0].message
print("finish:", resp.choices[0].finish_reason, "tool_calls:", bool(m.tool_calls))
if m.tool_calls:
    raw = m.tool_calls[0].function.arguments
    print("raw len:", len(raw))
    try:
        json.loads(raw)
        print("JSON OK")
    except Exception as exc:
        msg = str(exc)
        print("JSON ERR:", msg)
        import re
        mm = re.search(r"column (\d+)", msg)
        if mm:
            col = int(mm.group(1)) - 1
            print("context:", repr(raw[max(0,col-120):col+80]))

