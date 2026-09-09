from _main_experiment.config import LlmConfig
from _main_experiment.llm import MockBenchLlmClient, Usage


def test_mock_client_returns_arguments_and_usage():
    client = MockBenchLlmClient(
        responses=[{"answer": 42}],
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    result = client.call_strict_tool(
        messages=[{"role": "user", "content": "hi"}],
        tool_name="emit_result",
        tool_description="result",
        tool_schema={"type": "object"},
        config=LlmConfig(model="mock"),
    )
    assert result.arguments == {"answer": 42}
    assert result.usage.total_tokens == 15
