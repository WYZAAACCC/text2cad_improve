import os
import sys
sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process")
from openai import OpenAI
from seekflow_engineering_tools.generative_cad.authoring.tool_schemas import build_repair_patch_tool_schema

client = OpenAI(api_key=os.environ["GLM_API_KEY"], base_url="https://open.bigmodel.cn/api/paas/v4", timeout=60)
schema = build_repair_patch_tool_schema()

for thinking in [None, {"type": "disabled"}, {"type": "enabled"}]:
    ok = 0
    for i in range(3):
        try:
            kw = {"model": "glm-5.2",
                   "messages": [{"role": "user", "content": "修复 validation 错误：节点 n1 的 params 无效。输出一个修复补丁。"}],
                   "tools": [{"type": "function", "function": {"name": "emit_repair_patch", "description": "Local repair patch", "strict": False, "parameters": schema}}],
                   "tool_choice": "required", "max_tokens": 2048, "temperature": 0.3}
            if thinking is not None:
                kw["extra_body"] = {"thinking": thinking}
            resp = client.chat.completions.create(**kw)
            m = resp.choices[0].message
            if not m.tool_calls:
                print("thinking", thinking, "run", i, "NO TOOL CALL, content:", (m.content or "")[:80])
                continue
            args = m.tool_calls[0].function.arguments
            import json
            parsed = json.loads(args)
            missing = [k for k in ("changes", "reason") if k not in parsed]
            change_missing = None
            if "changes" in parsed and isinstance(parsed["changes"], list) and parsed["changes"]:
                change_missing = [k for k in ("path", "new_value", "reason") if k not in parsed["changes"][0]]
            ok += 1 if not missing and not change_missing else 0
            print("thinking", thinking, "run", i, "missing:", missing, change_missing, "raw head:", args[:100])
        except Exception as exc:
            print("thinking", thinking, "run", i, "ERR", str(exc)[:150])
    print("thinking", thinking, "=> tool+complete:", ok, "/3")

