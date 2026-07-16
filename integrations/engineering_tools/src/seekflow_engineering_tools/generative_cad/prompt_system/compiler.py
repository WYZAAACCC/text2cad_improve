"""PromptCompiler — 统一编排生产 prompt 组合并产出 PromptTrace.

行为冻结原则: compile_level1/compile_level2 复现 app/text-to-cad/server/main.py
原有拼接逻辑, 输出与旧实现**逐字节一致** (由 tests/generative_cad/prompt_system
回归测试锁定)。Compiler 引入的是: 统一入口 + fragment 追踪 + prompt hash。

select()/compile_generic 是未来分层 pack 的通用路径, 当前生产不使用。
"""
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.prompt_system.models import (
    FragmentUse,
    PromptTrace,
    text_hash,
)
from seekflow_engineering_tools.generative_cad.prompt_system.registry import (
    PromptRegistry,
    default_prompt_registry,
)

COMPILER_VERSION = "1.0.0"


class CompiledPrompt:
    """编译产物: messages + trace."""

    def __init__(self, system: str, user: str, trace: PromptTrace) -> None:
        self.system = system
        self.user = user
        self.trace = trace

    @property
    def messages(self) -> list[dict]:
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


class PromptCompiler:
    def __init__(self, registry: PromptRegistry | None = None) -> None:
        self.registry = registry or default_prompt_registry()

    # ---- 内部: trace 组装 ----
    def _use(self, fragment_id: str, reason: str) -> FragmentUse:
        f = self.registry.get(fragment_id)
        if f is None:
            raise KeyError(f"fragment not registered: {fragment_id}")
        return FragmentUse(
            id=f.id, version=f.version, source=f.source,
            reason=reason, hash=f.body_hash(),
        )

    def _finish(self, stage: str, system: str, user: str,
                uses: list[FragmentUse], request_id: str = "") -> CompiledPrompt:
        trace = PromptTrace(
            request_id=request_id, stage=stage,
            compiler_version=COMPILER_VERSION,
            selected_fragments=uses,
            system_prompt_hash=text_hash(system),
            user_prompt_hash=text_hash(user),
            system_prompt_chars=len(system),
            user_prompt_chars=len(user),
        )
        return CompiledPrompt(system, user, trace)

    # ============================================================
    # L1 路由 — 复现 main.py: build_level1_routing_prompt 直接产出
    # ============================================================
    def compile_level1(self, user_request: str, *, dialect_catalog: dict | None = None,
                       request_id: str = "") -> CompiledPrompt:
        from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
            build_level1_routing_prompt,
        )
        l1 = build_level1_routing_prompt(user_request, dialect_catalog=dialect_catalog)
        uses = [self._use("legacy.skills.level1_routing_system", "stage=routing (legacy production prompt)")]
        return self._finish("routing", l1["system"], l1["user"], uses, request_id)

    # ============================================================
    # L2 授权 — 复现 main.py _run_pipeline 的 user_parts 拼接, 逐字节一致
    # ============================================================
    def compile_level2(self, user_request: str, selection_plan, *,
                       spatial_context: str = "", request_id: str = "") -> CompiledPrompt:
        from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
            build_level2_authoring_prompt,
        )
        from seekflow_engineering_tools.generative_cad.prompt_system.fragments_legacy import (
            SERVER_L2_CONSTRAINTS_BLOCK,
        )

        l2 = build_level2_authoring_prompt(user_request, selection_plan)
        uses = [
            self._use("legacy.skills.level2_authoring_system", "stage=authoring (legacy production prompt)"),
            self._use("legacy.server.l2_constraints_block", "legacy always-injected server constraints"),
        ]

        # ---- 以下拼接逻辑原样移动自 main.py, 逐字节不变 ----
        user_parts = []

        # 1. 关键约束摘要
        user_parts.append(SERVER_L2_CONSTRAINTS_BLOCK)

        # 2. 使用指导
        usage = l2.get("usage_skills", {})
        if usage:
            usage_parts = ["\nDIALECT USAGE SKILLS:"]
            for dialect_id, skill_text in usage.items():
                usage_parts.append(f"\n--- {dialect_id} ---\n{skill_text[:2000]}")
            user_parts.append("\n".join(usage_parts))

        # 3. 反例
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

        # 4. 原始用户请求 + spatial context
        if spatial_context:
            user_parts.append(f"\nSPATIAL CONTRACT:\n{spatial_context}")
            uses.append(self._use(
                "legacy.server.spatial_dialect_guidance",
                "spatial_context provided (guidance text embedded in context by caller)"))
        user_parts.append(f"\nUSER REQUEST:\n{l2['user']}")

        user_content = "\n\n".join(user_parts)
        # ---- 拼接逻辑结束 ----

        return self._finish("authoring", l2["system"], user_content, uses, request_id)
