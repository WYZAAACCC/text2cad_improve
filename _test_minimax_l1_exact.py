import os
from openai import OpenAI

from seekflow_engineering_tools.generative_cad.skills.orchestrator import build_level1_routing_prompt, build_level1_tool
from seekflow_engineering_tools.generative_cad.dialects.registry import export_dialect_catalog

prompt = build_level1_routing_prompt(
    user_request="生成一个高压涡轮盘参考几何，外径500mm，中心孔直径120mm，轴向最大厚度76mm，轮毂半厚38mm，轮缘半厚30mm，保持原有主体结构，仅调整上述参数。参考几何，非适航件。",
    dialect_catalog=export_dialect_catalog(),
)
tool = build_level1_tool()

client = OpenAI(api_key=os.environ["MINIMAX_API_KEY"], base_url="https://api.minimax.chat/v1", timeout=120)
for i in range(3):
    try:
        resp = client.chat.completions.create(
            model="MiniMax-M3",
            messages=[{"role": "system", "content": prompt["system"]}, {"role": "user", "content": prompt["user"]}],
            tools=[{"type": "function", "function": {"name": tool["function"]["name"],
                                                    "description": tool["function"]["description"],
                                                    "strict": False,
                                                    "parameters": tool["function"]["parameters"]}}],
            tool_choice="required",
            temperature=0.3, top_p=0.9, seed=0, max_tokens=8192,
            extra_body={"thinking": {"type": "disabled"}},
        )
        m = resp.choices[0].message
        print("run", i, "finish:", resp.choices[0].finish_reason, "tool_calls:", bool(m.tool_calls))
    except Exception as exc:
        print("run", i, "FAIL:", str(exc)[:200])

