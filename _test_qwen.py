import os
from openai import OpenAI

key = os.environ.get("QWEN_API_KEY", "")
assert key, "no key"

for base in ["https://dashscope.aliyuncs.com/compatible-mode/v1"]:
    for model in ["qwen3.7-plus", "qwen-plus", "qwen3.8-max"]:
        try:
            client = OpenAI(api_key=key, base_url=base, timeout=30)
            resp = client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": "reply ok"}], max_tokens=20)
            print("OK", base, model, repr((resp.choices[0].message.content or "")[:40]))
        except Exception as exc:
            print("FAIL", base, model, str(exc)[:160])

