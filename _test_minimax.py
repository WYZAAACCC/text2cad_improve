import os
from openai import OpenAI

key = os.environ.get("MINIMAX_API_KEY", "")
assert key, "no key"

for base in ["https://api.minimax.chat/v1", "https://api.minimaxi.com/v1"]:
    for model in ["MiniMax-M3", "MiniMax-M2"]:
        try:
            client = OpenAI(api_key=key, base_url=base, timeout=30)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "reply ok"}],
                max_tokens=10,
            )
            print("OK", base, model, resp.choices[0].message.content)
        except Exception as exc:
            print("FAIL", base, model, str(exc)[:200])

