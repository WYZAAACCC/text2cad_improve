import time
from pathlib import Path
import urllib.request

url = "https://platform.minimaxi.com/document/openai-compatibility"
uas = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "curl/8.0",
]
for i in range(12):
    ua = uas[i % len(uas)]
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "text/html,*/*", "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
        if len(body) > 1000 and b"MiniMax" in body:
            Path(r"E:\text_to_cad_improve\auto_detection_process\_mm_doc.html").write_bytes(body)
            print("OK attempt", i, "bytes", len(body))
            break
        print("attempt", i, "code", r.status, "bytes", len(body))
    except Exception as exc:
        print("attempt", i, "ERR", str(exc)[:120])
    time.sleep(1)

