from pathlib import Path

ORCH = Path(r"E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src\seekflow_engineering_tools\generative_cad\repair_kernel\orchestrator.py")
PCH = Path(r"E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src\seekflow_engineering_tools\generative_cad\repair\patch.py")

def edit(p, old_lines, new_lines):
    s = p.read_text(encoding="utf-8")
    old = "\n".join(old_lines)
    new = "\n".join(new_lines)
    n = s.count(old)
    if n != 1:
        raise SystemExit("not unique: %s count=%d" % (p.name, n))
    p.write_text(s.replace(old, new), encoding="utf-8")

edit(ORCH, [
    "        return re.compile(rf\"^/nodes/{re.escape(m.group(1))}/params/.+$\")",
], [
    "        return re.compile(rf\"^/nodes/{re.escape(m.group(1))}/params(/.+)?$\")",
])

edit(PCH, [
    "        # /nodes/<node_id>/params/<field>",
    "        m = re.match(r\"^/nodes/([^/]+)/params/(.+)$\", path)",
    "        if m:",
], [
    "        # /nodes/<node_id>/params (replace entire params dict)",
    "        m = re.match(r\"^/nodes/([^/]+)/params$\", path)",
    "        if m:",
    "            node_id = m.group(1)",
    "            found = False",
    "            for node in updated.get(\"nodes\", []):",
    "                if node.get(\"id\") == node_id:",
    "                    current = node.get(\"params\", {})",
    "                    if not _old_value_matches(current, change.old_value):",
    "                        raise ValueError(",
    "                            f\"repair old_value mismatch at {path}: \"",
    "                            f\"expected {change.old_value!r}, got {current!r}\"",
    "                        )",
    "                    node[\"params\"] = change.new_value",
    "                    found = True",
    "                    break",
    "            if not found:",
    "                raise ValueError(f\"repair target node not found: {node_id}\")",
    "            applied += 1",
    "",
    "        # /nodes/<node_id>/params/<field>",
    "        m = re.match(r\"^/nodes/([^/]+)/params/(.+)$\", path)",
    "        if m:",
])

