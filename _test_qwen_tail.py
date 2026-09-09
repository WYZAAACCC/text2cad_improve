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
tools = [{"type": "function", "function": {"name": "run_python_code", "description": agentic_l2._GENERIC_CALC_TOOLS["run_python_code"]["description"], "strict": False, "parameters": agentic_l2._GENERIC_CALC_TOOLS["run_python_code"]["schema"]}}]
resp = client.chat.completions.create(model="qwen3.7-plus", messages=[{"role": "system", "content": agentic_l2.AGENT_A_SYSTEM}, {"role": "user", "content": user}], tools=tools, tool_choice="required", max_tokens=8192, temperature=0.3, seed=0, extra_body={})
m = resp.choices[0].message
raw = m.tool_calls[0].function.arguments
print("finish:", resp.choices[0].finish_reason, "len:", len(raw))
print("head:", raw[:150])
print("tail:", repr(raw[-160:]))

