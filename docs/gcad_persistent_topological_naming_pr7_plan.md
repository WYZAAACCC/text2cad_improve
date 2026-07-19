# PR 7 实施规划：PersistentTopoRef + Validation Pipeline 集成

> **前置：Phase 1-4 已交付 (77 tests, 0 failures)**
> **目标：将 topology validation 接入 validation_kernel，使拓扑检查在构建时实际运行**

---

## 0. 为什么先做 PR 7 而非 Phase 5

| 维度 | PR 7 (Validation 集成) | Phase 5 (Loft/Sweep + Fingerprint) |
|---|---|---|
| **风险** | 低 — 纯集成，不改 handler | 高 — 新 OCP wrapper + 复杂匹配算法 |
| **改动量** | ~100 行新增 | ~400+ 行 |
| **价值** | 立即生效 — 构建时输出拓扑诊断 | 需 Phase 6 配合才有可见价值 |
| **依赖** | 零新依赖 | 需要 loft/sweep handler 理解 |

---

## 1. 代码探查发现

### validation_kernel 架构
```
RuleRegistry.register_rule(manifest, evaluate_fn)
  → executor.run_validation(raw)
    → RAW_BARRIER_GROUPS (11 stages)
    → canonicalize()
    → CANONICAL_BARRIER_GROUPS (2 stages: dialect_semantics, geometry_preflight)
```

### 关键约束
- Validator 签名：`evaluate_fn(subject) -> ValidationReport`
- subject 是 `RawGcadDocument`(RAW stages) 或 `CanonicalGcadDocument`(CANONICAL stages)
- Topology 阶段需要 CanonicalGcadDocument + dialect registry（查 OperationSpec.topology_contract）
- 4 个拓扑阶段已在 `stages.py` 定义 ✅

---

## 2. PR 7 范围

### 新增文件 (1 个)

| 文件 | 内容 |
|---|---|
| `topology/kernel_validators.py` | Kernel-compatible validator wrapper: `validate_topology_contracts()`, `validate_topology_references()` |

### 修改文件 (3 个)

| 文件 | 修改 |
|---|---|
| `validation_kernel/legacy_adapter.py` | +2 个 topology CORE rule 注册 |
| `validation_kernel/stages.py` | TOPOLOGY_CONTRACT 加入 CANONICAL_BARRIER_GROUPS (作为 advisory 组) |
| `topology/__init__.py` | 导出 kernel_validators |

### 核心设计

```python
# topology/kernel_validators.py

def validate_topology_contracts(canonical: CanonicalGcadDocument) -> ValidationReport:
    """检查所有 geometry-producing operation 是否有 topology_contract。
    
    Phase 7: WARNING 级别 — 缺少 contract 仅警告，不阻止构建。
    Phase 8+: ERROR 级别 — 对高风险 consumer 强制要求。
    """
    issues = []
    for node in canonical.nodes:
        effect = _get_op_effects(node)  # 从 dialect registry 查
        if _is_geometry_op(effects):
            contract = _get_contract(node)  # 从 OperationSpec 查
            if contract is None:
                issues.append(ValidationIssue(
                    stage="topology_contract",
                    code="TOPOLOGY_CONTRACT_MISSING",
                    severity="warning",  # Phase 7: warning only
                    message=f"Node '{node.id}' ({node.dialect}.{node.op}) has no topology_contract",
                ))
    return ValidationReport(
        ok=True,  # Never fails build in Phase 7
        stage="topology_contract",
        issues=issues,
    )

def validate_topology_references(canonical: CanonicalGcadDocument) -> ValidationReport:
    """检查 Canonical IR 中的 PersistentTopoRef 是否有效。
    
    Phase 7: 当前 IR 还没有 PersistentTopoRef — 此 validator 为空壳，占位。
    Phase 8+: IR schema 升级后填入实际检查。
    """
    return ValidationReport(ok=True, stage="topology_reference", issues=[])
```

### Stage 编组

```python
# validation_kernel/stages.py

# 新增 advisory barrier group (放在 canonical 后面，不影响构建成败)
TOPOLOGY_ADVISORY_GROUP: tuple[tuple[ValidationStage, ...], ...] = (
    (ValidationStage.TOPOLOGY_CONTRACT,),
)

CANONICAL_BARRIER_GROUPS: tuple[tuple[ValidationStage, ...], ...] = (
    (ValidationStage.DIALECT_SEMANTICS, ValidationStage.GEOMETRY_PREFLIGHT),
    (ValidationStage.TOPOLOGY_CONTRACT,),  # NEW: advisory, never fails build
)
```

---

## 3. 实施顺序

```
7.1: topology/kernel_validators.py — 2 个 kernel-compatible 验证器
7.2: validation_kernel/legacy_adapter.py — 注册 2 个 topology CORE rules
7.3: validation_kernel/stages.py — TOPOLOGY_CONTRACT 加入 CANONICAL_BARRIER_GROUPS
7.4: topology/__init__.py — 导出 kernel_validators
7.5: 运行全部测试确保零回归
7.6: 写入 PR 7 测试
```

## 4. 验收标准

- [ ] `validate_topology_contracts()` 对缺少 contract 的 geometry op 产生 WARNING
- [ ] topology validation 在 validation_kernel 执行时实际运行
- [ ] 不阻止构建 (ok=True 即使有 warning)
- [ ] 77 已有测试零回归
