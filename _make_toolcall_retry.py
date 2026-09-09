from pathlib import Path

p = Path(r"E:\text_to_cad_improve\auto_detection_process\_main_experiment\llm.py")

def edit(old_lines, new_lines):
    s = p.read_text(encoding="utf-8")
    old = "\n".join(old_lines)
    new = "\n".join(new_lines)
    n = s.count(old)
    if n != 1:
        raise SystemExit("not unique count=%d" % n)
    p.write_text(s.replace(old, new), encoding="utf-8")

edit([
    "        message = response.choices[0].message",
    "        if not message.tool_calls:",
    "                \"model returned no tool call\",",
    "                code=\"provider_no_tool_call\",",
    "            )",
])

