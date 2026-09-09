from pathlib import Path

p = Path(r"E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src\seekflow_engineering_tools\generative_cad\repair_kernel\orchestrator.py")

def edit(old_lines, new_lines):
    s = p.read_text(encoding="utf-8")
    old = "\n".join(old_lines)
    new = "\n".join(new_lines)
    n = s.count(old)
    if n != 1:
        raise SystemExit("not unique count=%d" % n)
    p.write_text(s.replace(old, new), encoding="utf-8")

edit([
    "    params_re = re.compile(rf\"^/nodes/{re.escape(target_node_id)}/params/.+$\")",
    "    allowed_prefixes = tuple(allowed_paths)",
    "    for ch in patch.changes:",
    "        if not params_re.match(ch.path):",
    "            return False, f\"path {ch.path!r} outside target node params\"",
], [
    "    def _allowed_regex(p):",
    "        m = re.match(r\"^/nodes/([^/]+)/params\", p)",
    "        if not m:",
    "            return None",
    "        return re.compile(rf\"^/nodes/{re.escape(m.group(1))}/params/.+$\")",
    "    allowed_regexes = [r for r in (_allowed_regex(p) for p in allowed_paths) if r]",
    "    if not allowed_regexes:",
    "        allowed_regexes = [re.compile(rf\"^/nodes/{re.escape(target_node_id)}/params/.+$\")]",
    "    allowed_prefixes = tuple(allowed_paths)",
    "    for ch in patch.changes:",
    "        if not any(r.match(ch.path) for r in allowed_regexes):",
    "            return False, f\"path {ch.path!r} outside allowed repair node params\"",
])

