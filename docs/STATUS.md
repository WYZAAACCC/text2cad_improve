# V3 持久拓扑升级状态

> 最后更新: 2026-07-20
> 基线: `20a0b2a` → 当前 `63eafcc`

## 总体进度：10/10 Phase 完成

| Phase | Commit | Pass/Xfail | 关键成果 |
|-------|--------|-----------|---------|
| P0 | `1e6998d` | 3 + 13 xfail | 基线冻结 + 16 characterization tests |
| P1 | `54a2ad6` | 72 + 10 xfail | V3 身份模型 TopologyIdentityDescriptorV3 |
| P2 | `70eee37` | 82 + 2 xfail | Registry 严格解析 + lineage 闭包 |
| P3 | `3e56edb` | 95 + 2 xfail | ObjectStore revision + Locator V3 |
| P4 | `978282f` | 100 + 2 xfail | OperationSpec topology_mode 强制执行 |
| P5 | `47636db` | 105 + 2 xfail | Semantic naming evidence entity_type |
| P6 | `9773dc7` | 106 + 1 xfail | Matcher 严格化 (最后 P0) |
| P7 | `cc86899` | 107 + 0 xfail | CAE Bridge + Sidecar V3 |
| P8 | `d6c1726` | 107 + 0 xfail | 审计缺陷修复 (4 文件) |
| P9 | `63eafcc` | 107 + 0 xfail | Descriptor 存储 + Pipeline auto-sidecar |

**107 测试全部通过，0 xfails。**

## P0 问题：11/11 全部修复

| T-001 | ✅ | V3 统一身份模型 |
| T-002 | ✅ | V3 key 不含 producer_node_id |
| T-003 | ✅ | model_validator 拒绝非法状态 |
| T-004 | ✅ | resolve() 需要 ObjectStore |
| T-005 | ✅ | 修复 except:pass |
| T-006 | ✅ | RuntimeTopoLocator + is_stale_v3() |
| T-007 | ✅ | topology_mode="required" 强制 |
| T-008 | ✅ | CAE 空集合拒绝 + required_resolution |
| T-009 | ✅ | restore 设置 binding_state=UNBOUND |
| T-010 | ✅ | Matcher fingerprint_unique, never exact |
| T-011 | ✅ | 统一 _QUALITY_RANK |

## P1 问题：6/9 修复

| T-012 | ✅ | validate_integrity 10项检查 |
| T-013 | ✅ | delta 验证严格化 + unchanged |
| T-014 | ✅ | _infer_entity_type 使用 evidence |
| T-017 | ⚠️ | 指纹计算粗糙 (全局坐标) |
| T-018 | ⚠️ | Sidecar V3 缺 geometry SHA |
| T-019 | ✅ | 5 ops 连接 topology_contract |
| T-020 | ⚠️ | 缺 perturbation E2E 测试 |
| T-015 | ❌ | History builder 平行 (需 OCP 重构) |
| T-016 | ❌ | Boolean 拓扑后验命名 (需 OCCT 集成) |

## P2 问题：0/2 修复

| T-021 | ⚠️ | 多数 handler 使用后验命名 |
| T-022 | ❌ | cad_adapters v1 parser (需 SW 环境) |

## 有意延后的项目

1. **T-015 History wrapper 平行 builder** — 需将 20+ handler 从 CadQuery 重构为 OCP builder
2. **T-016 Boolean history** — 需从 OCCT Boolean Generated/Modified/IsDeleted 构建 split/merge
3. **T-022 CAD adapters** — 需 SolidWorks/NX 测试环境

## 已变更 20 个文件 (10 phases)

```
topology/ids.py, models.py, registry.py, locator.py
topology/shape_binding.py, transaction.py, matcher.py
topology/policies.py, cae_bridge.py, persistence.py
topology/semantic_naming.py
runtime/object_store.py, context.py
dialects/operation.py, executor.py, default_registry.py
pipeline/run.py
tests/.../topology_v3/ (7 test files)
docs/topology_v3_baseline.md, STATUS.md
```
