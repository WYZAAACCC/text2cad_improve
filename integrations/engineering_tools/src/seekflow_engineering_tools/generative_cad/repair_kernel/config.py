"""RepairLoopConfig — Repair Loop 统一配置 (repair_loop.md §4).

所有入口共享同一配置对象; 开关语义 (§4.1):
- enabled=False → 禁止一切 LLM repair (确定性 autofix 由
  deterministic_autofix_enabled 单独决定);
- enabled=True 但无 caller → 只执行确定性修复, 结果标记
  repair_unavailable, 不得声称 LLM repair 已启用。

只包含当前有消费者的字段; §4 其余字段 (wiring repair 许可、
byte/token/cost 预算等) 等实际需要时再加。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RepairLoopConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    validation_repair_enabled: bool = True
    runtime_repair_enabled: bool = True
    deterministic_autofix_enabled: bool = True

    max_validation_llm_attempts: int = 3
    max_runtime_llm_attempts: int = 2
    max_total_llm_attempts: int = 4

    max_changes_per_patch: int = 4
    max_relative_numeric_change: float = 0.25   # §10.3 数值修改预算
    max_absolute_patch_bytes: int = 16_384      # §4 补丁字节上限

    # §10.4: LLM patch 默认禁止改 required/degradation_policy (禁止降级掩盖失败);
    # 确定性策略降级 (auto_fixer fix_chamfer_fillet_optional) 不受此开关约束
    allow_degradation_change: bool = False
