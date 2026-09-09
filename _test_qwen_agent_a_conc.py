import os
import sys
import json
import threading
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process")
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server")
from openai import OpenAI
import agentic_l2

text = "生成一个修改后的高压涡轮盘参考几何，外径500mm，中心孔直径120mm，轴向最大厚度76mm，轮毂半厚38mm，轮缘半厚30mm，保持原有主体结构，仅调整上述参数。参考几何，非适航件。"
user = text + agentic_l2._append_parametric_block(text)
tool = {"type": "function", "function": {"name": "emit_design_plan", "description": "输出最终 AgentDesignPlan", "strict": False, "parameters": agentic_l2.AGENT_A_TOOL_SCHEMA}}
results = []
def work(i):
    try:
        client = OpenAI(api_key=os.environ["QWEN_API_KEY"], base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", timeout=90)
        resp = client.chat.completions.create(
            model="qwen3.7-plus",
            messages=[{"role": "system", "content": agentic_l2.AGENT_A_SYSTEM}, {"role": "user", "content": user}],
            tools=[tool], tool_choice="required", max_tokens=8192, temperature=0.3, seed=0, extra_body={},
        )
        m = resp.choices[0].message
        raw = m.tool_calls[0].function.arguments if m.tool_calls else ""
        ok = False
        err = ""
        if raw:
            try:
                json.loads(raw)
                ok = True
            except Exception as exc:
                err = str(exc)[:80]
        results.append((i, bool(m.tool_calls), ok, err, len(raw)))
    except Exception as exc:
        results.append((i, False, False, "call:" + str(exc)[:80], 0))
threads = [threading.Thread(target=work, args=(i,)) for i in range(10)]
for t in threads: t.start()
for t in threads: t.join()
for r in sorted(results): print(r)

