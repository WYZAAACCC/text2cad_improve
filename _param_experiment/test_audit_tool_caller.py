"""临时验证：_AuditToolCaller（逐次工具调用轨迹）+ _write_pipeline_log 扩展。"""
import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))

import main  # noqa: E402
from seekflow_engineering_tools.generative_cad.llm.provider import ToolCallResult  # noqa: E402


class _FakeInner:
    def __init__(self, fail=False):
        self.fail = fail
        self.last_kw = None

    def call_strict_tool(self, **kw):
        self.last_kw = kw
        if self.fail:
            raise RuntimeError("simulated llm failure")
        return ToolCallResult(
            tool_name=kw["tool_name"], arguments={"nodes": [{"id": "n1"}, {"id": "n2"}],
                                                  "components": []},
            raw_response_id="resp_123", model="deepseek-v4-pro", provider="deepseek")


# ── 1. 成功路径 ──
audit = []
inner = _FakeInner()
w = main._AuditToolCaller(inner, audit)
r = w.call_strict_tool(
    messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}],
    tool_name="g_cad_core", tool_description="d", tool_schema={"type": "object"},
    model_config=type("MC", (), {"model": "deepseek-v4-pro"}))
assert r.arguments["nodes"][0]["id"] == "n1", "返回透传失败"
assert len(audit) == 1
rec = audit[0]
assert rec["ok"] is True and rec["tool_name"] == "g_cad_core"
assert rec["prompt_chars"] == 6 and rec["prompt_hash"].startswith("sha256:")
assert rec["result_keys"] == ["components", "nodes"] and rec["result_size"] > 0
assert rec["result_hash"].startswith("sha256:")
assert isinstance(rec["elapsed_s"], float)
assert "prompt_messages" not in rec, "L1/L2 不应内联全文"
assert rec["raw_response_id"] == "resp_123"
print("wrapper 成功路径 PASS  rec =", {k: v for k, v in rec.items() if k != "prompt_messages"})

# ── 2. repair 调用内联全文 ──
audit2 = []
w2 = main._AuditToolCaller(_FakeInner(), audit2)
w2.call_strict_tool(
    messages=[{"role": "system", "content": "REPAIR_SYS"}, {"role": "user", "content": "fix it"}],
    tool_name="emit_repair_patch", tool_description="Local repair patch",
    tool_schema={"type": "object"}, model_config=type("MC", (), {"model": "deepseek-v4-pro"}))
assert audit2[0].get("prompt_messages") == [
    {"role": "system", "content": "REPAIR_SYS"}, {"role": "user", "content": "fix it"}]
print("wrapper repair 内联全文 PASS")

# ── 3. 异常透传 ──
audit3 = []
w3 = main._AuditToolCaller(_FakeInner(fail=True), audit3)
try:
    w3.call_strict_tool(messages=[], tool_name="select_dialect_plan", tool_description="d",
                        tool_schema={}, model_config=type("MC", (), {"model": "m"}))
    raise AssertionError("应抛异常")
except RuntimeError as exc:
    assert "simulated llm failure" in str(exc), "异常应原样透传"
assert audit3[0]["ok"] is False and "RuntimeError" in audit3[0]["error"]
print("wrapper 异常透传 PASS  error =", audit3[0]["error"])

# ── 4. _write_pipeline_log 扩展：tool_calls.json + 统计 ──
with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    main._write_pipeline_log(d, ok=True, stages={"route": "generative_cad_ir"},
                             tool_audit=audit + audit2)
    log = json.loads((d / "pipeline_log.json").read_text(encoding="utf-8"))
    tc = log["tool_calls"]
    assert tc["count"] == 2 and tc["ok"] == 2 and tc["failed"] == 0
    assert isinstance(tc["total_elapsed_s"], float)
    calls = json.loads((d / "tool_calls.json").read_text(encoding="utf-8"))
    assert len(calls) == 2 and calls[1]["tool_name"] == "emit_repair_patch"
    assert calls[1]["prompt_messages"][1]["content"] == "fix it"
    print("helper tool_calls 落盘 + 统计 PASS  count =", tc["count"], "elapsed =", tc["total_elapsed_s"])

print("ALL OK")
