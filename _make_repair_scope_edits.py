from pathlib import Path

PB = Path(r"E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src\seekflow_engineering_tools\generative_cad\authoring\prompt_builders.py")
ORCH = Path(r"E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src\seekflow_engineering_tools\generative_cad\repair_kernel\orchestrator.py")

def edit(p, old_lines, new_lines):
    s = p.read_text(encoding="utf-8")
    old = "\n".join(old_lines)
    new = "\n".join(new_lines)
    n = s.count(old)
    if n != 1:
        raise SystemExit("not unique: %s count=%d" % (p.name, n))
    p.write_text(s.replace(old, new), encoding="utf-8")

# 1. prompt_builders: add related_contracts parameter
edit(PB, [
    "    user_request: str = \"\",",
    ") -> str:",
], [
    "    user_request: str = \"\",",
    "    related_contracts: list[str] | None = None,",
    ") -> str:",
])

# 2. prompt_builders: render related contracts block
edit(PB, [
    "OPERATION CONTRACT:",
    "{op_contract}",
    "",
    "GEOMETRY HEALTH:",
], [
    "OPERATION CONTRACT:",
    "{op_contract}",
    "",
    "RELATED NODE CONTRACTS (you may also adjust their params when directly causal):",
    "{compact_json(related_contracts or [])}",
    "",
    "GEOMETRY HEALTH:",
])

# 3. orchestrator: expand allowed paths through input chain and pass related contracts
edit(ORCH, [
    "            prompt = build_runtime_repair_user_prompt(",
    "                current_doc=current,",
    "                runtime_issues=[i.model_dump(mode=\"json\") for i in report.issues],",
    "                failing_node=failing_node,",
    "                op_contract=op_contract,",
    "                geometry_health=report.geometry_health,",
    "                allowed_paths=cls.allowed_paths,",
    "                prior_attempts=prior_runtime_attempts,",
    "                user_request=user_request,",
    "            )",
], [
    "            allowed_paths = list(cls.allowed_paths)",
    "            related_contracts: list[str] = []",
    "            if failing_node is not None and dialect_registry is not None:",
    "                collected: set[str] = set()",
    "",
    "                def _collect_input_nodes(node_id: str, depth: int) -> None:",
    "                    if node_id in collected or depth > 8:",
    "                        return",
    "                    collected.add(node_id)",
    "                    node = next((n for n in current.get(\"nodes\", [])",
    "                                 if n.get(\"id\") == node_id), None)",
    "                    if node is None:",
    "                        return",
    "                    allowed_paths.append(f\"/nodes/{node_id}/params\")",
    "                    plan = SimpleNamespace(dialect=node.get(\"dialect\", \"\"),",
    "                                           op=node.get(\"op\", \"\"),",
    "                                           op_version=node.get(\"op_version\", \"1.0.0\"))",
    "                    related_contracts.append(_build_op_contract(plan, dialect_registry))",
    "                    for inp in node.get(\"inputs\", []):",
    "                        _collect_input_nodes(inp.get(\"node\", \"\"), depth + 1)",
    "",
    "                _collect_input_nodes(cls.target_node_id or \"\", 0)",
    "",
    "            prompt = build_runtime_repair_user_prompt(",
    "                current_doc=current,",
    "                runtime_issues=[i.model_dump(mode=\"json\") for i in report.issues],",
    "                failing_node=failing_node,",
    "                op_contract=op_contract,",
    "                related_contracts=related_contracts,",
    "                geometry_health=report.geometry_health,",
    "                allowed_paths=allowed_paths,",
    "                prior_attempts=prior_runtime_attempts,",
    "                user_request=user_request,",
    "            )",
])

# 4. orchestrator: use expanded allowed_paths in runtime patch policy
edit(ORCH, [
    "            ok_policy, why = check_runtime_patch(",
    "                patch, target_node_id=cls.target_node_id or \"\",",
    "                allowed_paths=cls.allowed_paths, cfg=cfg)",
], [
    "            ok_policy, why = check_runtime_patch(",
    "                patch, target_node_id=cls.target_node_id or \"\",",
    "                allowed_paths=allowed_paths, cfg=cfg)",
])

