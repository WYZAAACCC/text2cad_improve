import sys
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process")
from _main_experiment.llm import OpenAICompatToolClient
from _main_experiment.config import LlmConfig

cfg = LlmConfig(
    provider="openai_compat", model="MiniMax-M3",
    base_url="https://api.minimax.chat/v1", api_key_env="MINIMAX_API_KEY",
    temperature=0.3, max_tokens=512,
)
client = OpenAICompatToolClient()
schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
try:
    res = client.call_strict_tool(
        messages=[{"role": "user", "content": "reply ok"}],
        tool_name="emit_result", tool_description="emit result", tool_schema=schema,
        config=cfg,
    )
    print("OK arguments:", res.arguments)
    print("model:", res.model, "provider:", res.provider)
except Exception as exc:
    print("FAIL:", str(exc)[:500])

