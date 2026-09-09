import os
from openai import OpenAI

key = os.environ.get("GLM_API_KEY", "")
assert key, "no key"

for base in ["https://open.bigmodel.cn/api/paas/v4"]:
    for model in ["glm-5.3", "glm-5", "glm-4.7", "glm-4.6", "glm-4.5"]:
        try:
            client = OpenAI(api_key=key, base_url=base, timeout=30)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "reply ok"}],
                max_tokens=10,
            )
            print("OK", base, model, (resp.choices[0].message.content or "")[:30])
        except Exception as exc:
            print("FAIL", base, model, str(exc)[:160])

