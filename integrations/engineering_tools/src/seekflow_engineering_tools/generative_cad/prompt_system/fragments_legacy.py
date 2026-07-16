"""Legacy 生产 prompt 的 fragment 登记 — 引用原定义, 零复制.

铁律: 已能稳定生成模型的提示词内容不改变。因此:
- skills/prompts.py 中的 L1/L2/Repair 系统提示词用 body_ref 引用原常量;
- 原内联在 app/text-to-cad/server/main.py 的两个字符串块 (L2 约束块、空间
  方言指引) **原样移动**到本文件作为常量 (内容逐字节不变, 仅改变存放位置),
  main.py 改为从这里引用;
- 领域技能 markdown 用 body_ref 引用 loader — 当前生产路径不注入它们,
  登记仅为未来分层选择做准备, 不改变现有行为。
"""
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.prompt_system.models import PromptFragment
from seekflow_engineering_tools.generative_cad.prompt_system.registry import PromptRegistry

# ============================================================
# 原样移动自 app/text-to-cad/server/main.py (_run_pipeline L2 authoring 段)
# 内容逐字节不变 — 铁律。未来拆分为 part.turbine_disc / feature.fir_tree_slot
# pack 时, 必须走回归测试, 不得直接修改本字符串。
# ============================================================
SERVER_L2_CONSTRAINTS_BLOCK = (
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

# 原样移动自 main.py (_run_pipeline spatial context 段) — 内容逐字节不变
SERVER_SPATIAL_DIALECT_GUIDANCE = (
    "\n\nDIALECT GUIDANCE (spatial context is provided — use general CAD operations):\n"
    "- For axisymmetric disk bodies: use sketch_profile dialect with "
    "create_2d_sketch(plane=XZ) → add_polyline(R-Z polygon) → close_profile → revolve_profile.\n"
    "- Do NOT use axisymmetric.revolve_profile — it Z-sorts stations and cannot express "
    "thickness-by-radius profiles (hub thick → web thin → rim thick).\n"
    "- For slot features: sketch_profile → create_2d_sketch → add_polyline → "
    "close_profile → fillet_sketch → mirror_profile → extrude_profile.\n"
    "- For patterning and assembly: composition → circular_pattern_component(rotate_copies=True) "
    "→ boolean_cut.\n"
    "- The spatial constraints above describe positioning; the dialect guidance above "
    "describes HOW to build each component. Use sketch_profile + composition, NOT axisymmetric.\n"
)


def _level1_system() -> str:
    from seekflow_engineering_tools.generative_cad.skills.prompts import (
        LEVEL1_ROUTING_SYSTEM_PROMPT,
    )
    return LEVEL1_ROUTING_SYSTEM_PROMPT


def _level2_system() -> str:
    from seekflow_engineering_tools.generative_cad.skills.prompts import (
        LEVEL2_AUTHORING_SYSTEM_PROMPT,
    )
    return LEVEL2_AUTHORING_SYSTEM_PROMPT


def _repair_patch_system_v2() -> str:
    from seekflow_engineering_tools.generative_cad.skills.prompts import (
        REPAIR_PATCH_SYSTEM_PROMPT_V2,
    )
    return REPAIR_PATCH_SYSTEM_PROMPT_V2


def _domain_skill_loader(skill_id: str):
    def _load() -> str:
        from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
            load_domain_skill,
        )
        return load_domain_skill(skill_id)
    return _load


def register_legacy_fragments(reg: PromptRegistry) -> None:
    reg.register(PromptFragment(
        id="legacy.skills.level1_routing_system",
        version="1.0.0", layer="legacy", stages=("routing",),
        source="generative_cad.skills.prompts:LEVEL1_ROUTING_SYSTEM_PROMPT",
        body_ref=_level1_system,
    ))
    reg.register(PromptFragment(
        id="legacy.skills.level2_authoring_system",
        version="1.0.0", layer="legacy", stages=("authoring",),
        source="generative_cad.skills.prompts:LEVEL2_AUTHORING_SYSTEM_PROMPT",
        body_ref=_level2_system,
    ))
    reg.register(PromptFragment(
        id="legacy.skills.repair_patch_system_v2",
        version="1.0.0", layer="legacy", stages=("repair",),
        source="generative_cad.skills.prompts:REPAIR_PATCH_SYSTEM_PROMPT_V2",
        body_ref=_repair_patch_system_v2,
    ))
    reg.register(PromptFragment(
        id="legacy.server.l2_constraints_block",
        version="1.0.0", layer="legacy", stages=("authoring",),
        # 已知包含涡轮盘专有知识 — 未来应拆入 part/feature pack (方案 P2),
        # 但铁律要求当前逐字节保留并恒注入
        tags=("turbine_disc", "fir_tree_slot"),
        source="prompt_system.fragments_legacy:SERVER_L2_CONSTRAINTS_BLOCK (moved from server/main.py)",
        body=SERVER_L2_CONSTRAINTS_BLOCK,
    ))
    reg.register(PromptFragment(
        id="legacy.server.spatial_dialect_guidance",
        version="1.0.0", layer="legacy", stages=("authoring",),
        tags=("spatial",),
        source="prompt_system.fragments_legacy:SERVER_SPATIAL_DIALECT_GUIDANCE (moved from server/main.py)",
        body=SERVER_SPATIAL_DIALECT_GUIDANCE,
    ))
    # 领域技能 — 当前生产路径不注入 (与现状一致); 登记供未来分层选择
    reg.register(PromptFragment(
        id="domain.mechanical.core",
        version="1.0.0", layer="domain", tags=("mechanical",),
        source="generative_cad/skills/domain/generic_mechanical.md",
        body_ref=_domain_skill_loader("generic_mechanical"),
    ))
    reg.register(PromptFragment(
        id="domain.turbomachinery.reference",
        version="1.0.0", layer="domain", tags=("turbomachinery", "turbine_disc"),
        source="generative_cad/skills/domain/turbomachinery_reference.md",
        body_ref=_domain_skill_loader("turbomachinery_reference"),
    ))
