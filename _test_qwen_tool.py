import sys
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process")
from _main_experiment.llm import OpenAICompatToolClient
from _main_experiment.config import LlmConfig
from seekflow_engineering_tools.generative_cad.skills.orchestrator import build_level1_tool

cfg = LlmConfig(
    provider="openai_compat", model="qwen3.7-plus",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", api_key_env="QWEN_API_KEY",
    temperature=0.3, max_tokens=1024,
)
client = OpenAICompatToolClient()
tool = build_level1_tool()
try:
    res = client.call_strict_tool(
        messages=[{"role": "user", "content": "生成一个高压涡轮盘参考几何，外径500mm，中心孔直径120mm，轴向最大厚度76mm。参考几何，非适航件。"}],
        tool_name=tool["function"]["name"],
        tool_description=tool["function"]["description"],
        tool_schema=tool["function"]["parameters"],
        config=cfg,
    )
    print("OK arguments:", str(res.arguments)[:200])
except Exception as exc:
    print("FAIL:", str(exc)[:400])

