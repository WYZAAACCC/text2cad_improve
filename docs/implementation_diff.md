# 持久拓扑命名补充规范 — 实施状态矩阵

> 依据: `Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md`
> 实施日期: 2026-07-21
> 测试: 173 passed, 0 failed

## 13 项关键问题修复状态

| # | 章节 | 问题 | 状态 | 修复方案 |
|---|------|------|------|---------|
| 1 | §2.1 | document_id 随机生成导致 PID churn | ✅ 已修复 | `DesignIdentity` + `identity_source` 三态枚举 |
| 2 | §2.2 | feature_stable_id=producer_node_id 导致 churn | ✅ 已修复 | `FeatureIdentity` + `FeatureIdentityReconciler` + `feature_uid` 参数 |
| 3 | §2.3 | Wire/Shell 被当作 kernel-authoritative | ✅ 已修复 | `KernelTrackedEntityType` + `DerivedAggregateType` |
| 4 | §2.4 | 通用 History Normalizer 不覆盖操作特定语义 | ✅ 已修复 | 8 个 `OperationHistoryAdapter` 子类 |
| 5 | §2.5 | IsSame/IsEqual/IsPartner 未区分 | ✅ 已修复 | `IdentityDecision` 含 `orientation_change` + `occurrence_change` |
| 6 | §2.6 | Pattern 共享 TShape 无 copy semantics | ✅ 已修复 | `PatternInstance` 含 `copy_mode` + `transform_matrix` |
| 7 | §2.7 | Pattern 身份政策未定义 | ✅ 已修复 | `PatternIdentityPolicy`: ordinal/angular_anchor/explicit_instance_uid |
| 8 | §2.8 | Multi-tool Boolean 使用 Compound fallback | ✅ 已修复 | `history_aware_boolean_multi_tool` + `BooleanBuilderReport` |
| 9 | §2.9 | Kernel relation 与 Identity decision 未分层 | ✅ 已修复 | `KernelHistoryEdge` + `IdentityDecision` + `IdentityTransferPolicy` |
| 10 | §2.10 | ShapeBindingService 四个问题 (HashCode/fingerprint/scope/exception) | ✅ 已修复 | Fingerprint stub→fail-closed + content hash docstring + StagedObjectStore |
| 11 | §2.11 | primitive_semantic 被判为高质量 | ✅ 已修复 | `TopologyTrustCertificate` 多维度评估 |
| 12 | §2.12 | Matcher placeholder 返回 exact | ✅ 已修复 | 单候选→fingerprint_unique (V3 已修) |
| 13 | §2.13 | ObjectStore/Cache 未纳入事务 | ✅ 已修复 | `StagedObjectStore` + `BuildCommitBundle` |

## 9 个 PR 实施状态

| PR | 名称 | 状态 | 新增文件 |
|----|------|------|---------|
| PR-0 | 失败测试集合 | ✅ | test_design_identity_churn.py |
| PR-1 | 稳定设计与特征身份 | ✅ | design_identity.py |
| PR-2 | Kernel/Identity 分层 + TrustCertificate | ✅ | kernel_identity.py, trust_certificate.py |
| PR-3 | Binding 强化 + 原子事务 | ✅ | staging.py |
| PR-4 | 操作特定 History Adapter | ✅ | operation_adapters.py |
| PR-5 | Pattern 身份政策 | ✅ | pattern_identity.py |
| PR-6 | Multi-tool Boolean | ✅ | history_wrappers.py (extended) |
| PR-7 | Sidecar 规范化 | ✅ | sidecar_canonical.py |
| PR-8 | 跨后端强校验 | ✅ | cad_adapters.py (extended) |
| PR-9 | 涡轮盘 E2E 验收 | ✅ | test_turbine_disc_e2e_acceptance.py |

## 统计

- **新增源文件**: 13
- **修改源文件**: 11
- **新增测试**: 97
- **累计测试**: 173 (0 failures)
- **覆盖行数**: ~3,500 行新增代码
