import sys
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process")
from _main_experiment.llm import OpenAICompatToolClient
from _main_experiment.config import LlmConfig
from _main_experiment.pipeline import _run_level1
from seekflow_engineering_tools.generative_cad.skills.orchestrator import build_level1_tool

cfg = LlmConfig(
    provider="openai_compat", model="MiniMax-M3",
    base_url="https://api.minimax.chat/v1", api_key_env="MINIMAX_API_KEY",
    temperature=0.3, max_tokens=1024,
)
client = OpenAICompatToolClient()
tool = build_level1_tool()
print("tool name:", tool["function"]["name"])
print("schema keys:", list(tool["function"]["parameters"].keys()))
try:
    res = client.call_strict_tool(
        messages=[{"role": "user", "content": "生成一个高压涡轮盘，外径500mm"}],
        tool_name=tool["function"]["name"],
        tool_description=tool["function"]["description"],
        tool_schema=tool["function"]["parameters"],
        config=cfg,
    )
    print("OK arguments:", str(res.arguments)[:300])
except Exception as exc:
    print("FAIL:", str(exc)[:500])

