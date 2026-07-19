# Topology V3 基线文档 (Phase 0 Baseline)

> **创建日期**: 2026-07-20
> **目的**: V3 升级前锁定当前系统状态，为后续 Phase 1-9 提供可比较基线

---

## 1. 环境快照

| 项目 | 值 |
|------|-----|
| Git SHA | `20a0b2a` (docs: update README and architecture doc for topology naming system) |
| Python | 3.13.5 (Anaconda, Windows 11) |
| CadQuery | ❌ 当前环境未安装 (测试仅限纯模型测试) |
| OCP/OCCT | ❌ 当前环境未安装 |
| pytest | 8.3.4 |
| OS | Windows 11 Home China 10.0.22631 |

## 2. 关键拓扑模块文件清单

| 文件 | 行数(估算) | 职责 |
|------|-----------|------|
| `topology/ids.py` | 229 | v1/v2 PersistentTopoId, key 生成 |
| `topology/models.py` | 204 | EntityRecord, Delta, Resolution, NamedTopologySet |
| `topology/registry.py` | 734 | 中央注册表, resolve(), apply_delta(), 完整性检查 |
| `topology/locator.py` | ~80 | RuntimeTopoLocator (IndexedMap 定位) |
| `topology/shape_binding.py` | 338 | BodyTopologyMaps, locate/resolve/verify |
| `topology/transaction.py` | ~100 | TopologyTransaction (原子 commit/rollback) |
| `topology/semantic_naming.py` | ~600 | 11 个语义命名函数 |
| `topology/history_wrappers.py` | ~500 | 10 个 OCCT history wrapper |
| `topology/contracts.py` | ~120 | TopologyContract 预定义 |
| `topology/fingerprint.py` | ~80 | FaceFingerprint (占位) |
| `topology/matcher.py` | 234 | ConstrainedTopologyMatcher (cost=0 占位) |
| `topology/policies.py` | 176 | ConsumerPolicy, ResolutionQuality |
| `topology/cae_bridge.py` | 269 | resolve_named_set_to_faces(), cae_preflight_gate() |
| `topology/persistence.py` | 263 | Sidecar v2 write/read/rebind |
| `topology/cad_adapters.py` | ~200 | SW/NX/STEP 适配器 |
| `topology/kernel_validators.py` | ~100 | 拓扑契约 + 引用校验 |
| `topology/validation.py` | ~80 | 4 个拓扑校验规则 |
| `topology/repair_errors.py` | ~60 | 20 个标准拓扑错误码 |
| `dialects/executor.py` | ~500 | 统一执行器 (含 _apply_topology_delta_if_present) |

## 3. 现有测试结果

### 纯模型测试 (不需要 CadQuery)

```
tests/generative_cad/topology_baseline/test_topology_baseline.py: 21 passed, 5 skipped
tests/generative_cad/topology_baseline/test_topology_phase2.py: 25 passed, 5 failed (ImportError: cadquery)
```

**总计**: 46 passed, 5 failed, 5 skipped

失败的 5 个测试全部是 `ModuleNotFoundError: No module named 'cadquery'`，非代码逻辑错误。

### 需要 CadQuery 的测试 (当前环境不可运行)

- `test_topology_phase3.py` ~ `test_topology_phase7.py` — 需要在安装了 CadQuery 的环境中运行

## 4. 已审计确认的 P0 问题 (11 项)

| 编号 | 文件 | 问题摘要 | 审计结论 |
|------|------|---------|---------|
| T-001 | `ids.py` | v1/v2 两套 ID 语义并存，无统一迁移策略 | ✅ 确认 |
| T-002 | `ids.py:to_key()` | v2 hash 包含 document_id, producer_node_id 等易变字段 | ✅ 确认 |
| T-003 | `models.py` | active 可无 locator，exact 可无 evidence | ✅ 确认 |
| T-004 | `registry.py:resolve()` | 非严格路径 (无 ObjectStore) 对 active 直接返回 exact | ✅ 确认 |
| T-005 | `registry.py:L386-401` | `_reconstruct_locator` 调用在错误的对象上 + `except Exception: pass` | ✅ 确认 |
| T-006 | `shape_binding.py` | IndexedMap pos 无 revision 绑定，hash 计算弱 | ✅ 确认 |
| T-007 | `executor.py` | 拓扑 delta 失败 non-fatal (warning only) | ✅ 确认 |
| T-008 | `cae_bridge.py` | resolve_named_set_to_faces 不传 object_store/binding_service | ✅ 确认 |
| T-009 | `persistence.py` | restore_snapshot 后 active 无 locator 仍可 resolve exact | ✅ 确认 |
| T-010 | `matcher.py` | rank_candidates 所有 cost=0，单候选直接 exact | ✅ 确认 |
| T-011 | `policies.py` | `_QUALITY_RANK.get(..., 0)` 未知 quality 默认为 0 | ✅ 确认 |

## 5. Characterization Tests 列表

Phase 0 新增 15 个测试用例，预期大部分在当前代码上 **FAIL**（证明问题存在），后续 Phase 修复后全部 PASS。

详见: `tests/generative_cad/topology_v3/` (3 个文件)

### 预期结果矩阵

| # | 测试文件 | 测试名 | 当前预期 |
|---|---------|--------|---------|
| 1 | test_identity_model | `test_v2_key_changes_when_node_renamed` | **FAIL** |
| 2 | test_identity_model | `test_active_unbound_entity_never_resolves_exact` | **FAIL** |
| 3 | test_identity_model | `test_runtime_index_token_rejected_in_semantic_role` | **FAIL** |
| 4 | test_registry_strict_resolution | `test_resolve_without_binding_context_returns_exact` | **PASS** (基线) |
| 5 | test_registry_strict_resolution | `test_strict_resolve_rejects_stale_owner_revision` | **FAIL** |
| 6 | test_registry_strict_resolution | `test_strict_resolve_rejects_wrong_entity_type` | **FAIL** |
| 7 | test_registry_strict_resolution | `test_locator_swap_is_detected` | **FAIL** |
| 8 | test_registry_strict_resolution | `test_sidecar_restore_requires_rebind` | **FAIL** |
| 9 | test_registry_strict_resolution | `test_recursive_terminal_lineage_closure` | **FAIL** |
| 10 | test_registry_strict_resolution | `test_unknown_delta_source_is_fatal` | **FAIL** |
| 11 | test_registry_strict_resolution | `test_unchanged_relation_is_applied` | **FAIL** |
| 12 | test_matcher_and_policies | `test_single_fingerprint_candidate_is_not_kernel_exact` | **FAIL** |
| 13 | test_matcher_and_policies | `test_symmetric_candidates_remain_ambiguous` | **FAIL** |
| 14 | test_matcher_and_policies | `test_unknown_consumer_policy_is_denied` | **PASS** (当前默认较严) |
| 15 | test_matcher_and_policies | `test_empty_cae_named_set_is_fatal` | **FAIL** |

## 6. 下一步

Phase 1: 实现 V3 身份模型 (TopologyIdentityDescriptorV3 + key canonicalization)
