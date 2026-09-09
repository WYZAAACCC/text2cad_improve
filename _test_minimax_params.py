import os
from openai import OpenAI

from seekflow_engineering_tools.generative_cad.skills.orchestrator import build_level1_routing_prompt, build_level1_tool
from seekflow_engineering_tools.generative_cad.dialects.registry import export_dialect_catalog

prompt = build_level1_routing_prompt(
    user_request="生成一个高压涡轮盘参考几何，外径500mm，中心孔直径120mm，轴向最大厚度76mm，轮毂半厚38mm，轮缘半厚30mm。参考几何，非适航件。",
    dialect_catalog=export_dialect_catalog(),
)
tool = build_level1_tool()

client = OpenAI(api_key=os.environ["MINIMAX_API_KEY"], base_url="https://api.minimax.chat/v1", timeout=120)

def run(tag, kwargs):
    ok = 0
    for i in range(3):
        try:
            resp = client.chat.completions.create(
                model="MiniMax-M3",
                messages=[{"role": "system", "content": prompt["system"]}, {"role": "user", "content": prompt["user"]}],
                tools=[{"type": "function", "function": {"name": tool["function"]["name"],
                                                        "description": tool["function"]["description"],
                                                        "strict": False,
                                                        "parameters": tool["function"]["parameters"]}}],
                **kwargs,
            )
            ok += 1 if resp.choices[0].message.tool_calls else 0
        except Exception as exc:
            print(tag, "ERR", str(exc)[:120])
    print(tag, "tool_calls:", ok, "/3")

base = {"tool_choice": "required", "temperature": 0.3, "max_tokens": 1024, "extra_body": {"thinking": {"type": "disabled"}}}
run("required_no_seed", dict(base))
run("required_seed0", dict(base, seed=0))
run("required_no_top", dict(base, seed=0, top_p=0.9))
run("required_all", dict(base, seed=0, top_p=0.9, max_tokens=8192))
run("auto_all", dict(base, seed=0, top_p=0.9, max_tokens=8192, tool_choice="auto"))

