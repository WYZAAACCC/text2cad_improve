"""回归测试: PromptCompiler 输出必须与旧 main.py 拼接逻辑逐字节一致.

铁律: 已能稳定生成模型的提示词内容不改变。本测试把 main.py 原拼接逻辑
作为 golden 副本冻结在此, compiler 的任何行为偏移都会在这里失败。
"""
from __future__ import annotations
import pytest

from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
    build_level1_routing_prompt,
    build_level2_authoring_prompt,
)
from seekflow_engineering_tools.generative_cad.skills.schemas import (
    DialectSelectionItem,
    DialectSelectionPlan,
)
from seekflow_engineering_tools.generative_cad.prompt_system import (
    PromptCompiler,
    default_prompt_registry,
)

USER_TEXT = "生成一个高压涡轮盘, 外径500mm, 60个枞树形榫槽"
SPATIAL_CTX = "COMPONENTS: disc(1), cutter(60)\nCONSTRAINTS: pattern 6deg"


def _plan() -> DialectSelectionPlan:
    return DialectSelectionPlan(
        part_intent={"object_type": "turbine_disc", "dominant_geometry": "axisymmetric",
                     "engineering_domain": "turbomachinery"},
        route_decision="generative_cad_ir",
        selected_dialects=[
            DialectSelectionItem(dialect="sketch_profile", version="0.2.0", reason="t"),
            DialectSelectionItem(dialect="composition", version="0.2.0", reason="t"),
        ],
        safety_notes=[],
    )


# ---- golden: 原样复制自 app/text-to-cad/server/main.py _run_pipeline ----
def _golden_l2_user_content(text: str, plan, spatial_context: str) -> tuple[str, str]:
    l2 = build_level2_authoring_prompt(text, plan)
    user_parts = []
    constraints_block = (
        "CRITICAL MODELING CONSTRAINTS:\n"
        "- For axisymmetric disk bodies with varying thickness (hub thick→web thin→rim thick):\n"
        "  use sketch_profile: create_2d_sketch(plane=XZ) → add_polyline(R-Z polygon points) → close_profile → revolve_profile\n"
        "  NOT axisymmetric.revolve_profile (Z-sorts stations, cannot express thickness-by-radius profiles)\n"
        "- For fir-tree slot cutters: sketch_profile → create_2d_sketch(plane=XY) → add_polyline (neck/lobe alternation)\n"
        "  → close_profile → fillet_sketch → mirror_profile → extrude_profile\n"
        "- For patterning: composition → circular_pattern_component(rotate_copies=True) → boolean_cut\n"
        "- Every sketch_profile component MUST include the complete chain: sketch → polyline → close → extrude/revolve\n"
        "- Every component root_node must be a node that exists and outputs body:solid\n"
        "- Do NOT use axisymmetric.revolve_profile for thickness-by-radius profiles"
    )
    user_parts.append(constraints_block)
    usage = l2.get("usage_skills", {})
    if usage:
        usage_parts = ["\nDIALECT USAGE SKILLS:"]
        for dialect_id, skill_text in usage.items():
            usage_parts.append(f"\n--- {dialect_id} ---\n{skill_text[:2000]}")
        user_parts.append("\n".join(usage_parts))
    anti = l2.get("anti_examples", {})
    if anti:
        anti_parts = ["\nANTI-EXAMPLES (DO NOT replicate):"]
        for dialect_id, examples in anti.items():
            for ex in examples[:3]:
                title = ex.get("title", "")
                expl = ex.get("explanation", "")
                correct = ex.get("correct_approach", "")
                anti_parts.append(f"- {title}: {expl}")
                if correct:
                    anti_parts.append(f"  Correct: {correct}")
        user_parts.append("\n".join(anti_parts))
    if spatial_context:
        user_parts.append(f"\nSPATIAL CONTRACT:\n{spatial_context}")
    user_parts.append(f"\nUSER REQUEST:\n{l2['user']}")
    return l2["system"], "\n\n".join(user_parts)


def test_compile_level1_byte_identical():
    reg = default_registry()
    catalog = reg.export_catalog()
    golden = build_level1_routing_prompt(USER_TEXT, dialect_catalog=catalog)
    cp = PromptCompiler().compile_level1(USER_TEXT, dialect_catalog=catalog)
    assert cp.system == golden["system"]
    assert cp.user == golden["user"]
    assert cp.messages[0] == {"role": "system", "content": golden["system"]}
    assert cp.messages[1] == {"role": "user", "content": golden["user"]}


@pytest.mark.parametrize("spatial", ["", SPATIAL_CTX])
def test_compile_level2_byte_identical(spatial):
    plan = _plan()
    g_system, g_user = _golden_l2_user_content(USER_TEXT, plan, spatial)
    cp = PromptCompiler().compile_level2(USER_TEXT, plan, spatial_context=spatial)
    assert cp.system == g_system
    assert cp.user == g_user


def test_trace_records_fragments_and_hashes():
    plan = _plan()
    cp = PromptCompiler().compile_level2(USER_TEXT, plan, spatial_context=SPATIAL_CTX)
    ids = [f.id for f in cp.trace.selected_fragments]
    assert "legacy.skills.level2_authoring_system" in ids
    assert "legacy.server.l2_constraints_block" in ids
    assert "legacy.server.spatial_dialect_guidance" in ids
    assert cp.trace.system_prompt_hash.startswith("sha256:")
    assert cp.trace.user_prompt_hash.startswith("sha256:")
    assert cp.trace.compiler_version


def test_legacy_fragments_reference_original_constants():
    """legacy fragment 的 body 必须与原常量对象逐字节一致 (引用而非复制)."""
    from seekflow_engineering_tools.generative_cad.skills.prompts import (
        LEVEL1_ROUTING_SYSTEM_PROMPT,
        LEVEL2_AUTHORING_SYSTEM_PROMPT,
        REPAIR_PATCH_SYSTEM_PROMPT_V2,
    )
    reg = default_prompt_registry()
    assert reg.get("legacy.skills.level1_routing_system").resolve_body() == LEVEL1_ROUTING_SYSTEM_PROMPT
    assert reg.get("legacy.skills.level2_authoring_system").resolve_body() == LEVEL2_AUTHORING_SYSTEM_PROMPT
    assert reg.get("legacy.skills.repair_patch_system_v2").resolve_body() == REPAIR_PATCH_SYSTEM_PROMPT_V2


def test_registry_conflict_fail_closed():
    from seekflow_engineering_tools.generative_cad.prompt_system.models import PromptFragment
    from seekflow_engineering_tools.generative_cad.prompt_system.registry import (
        PromptRegistry,
        PromptRegistryError,
    )
    r = PromptRegistry()
    r.register(PromptFragment(id="a", tags=("x",), body="A"))
    r.register(PromptFragment(id="b", tags=("x",), excludes=("a",), body="B"))
    with pytest.raises(PromptRegistryError):
        r.select(tags={"x"})
