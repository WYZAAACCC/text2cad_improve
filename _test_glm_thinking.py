import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["GLM_API_KEY"], base_url="https://open.bigmodel.cn/api/paas/v4", timeout=30)

variants = [
    None,
    {"thinking": {"type": "low"}},
    {"thinking": {"type": "high"}},
    {"thinking": {"type": "max"}},
    {"thinking": "low"},
]
for v in variants:
    try:
        kw = {"model": "glm-5.3", "messages": [{"role": "user", "content": "reply ok"}], "max_tokens": 20}
        if v is not None:
            kw["extra_body"] = v
        resp = client.chat.completions.create(**kw)
        print("OK", v, repr((resp.choices[0].message.content or "")[:30]))
    except Exception as exc:
        print("FAIL", v, str(exc)[:160])

