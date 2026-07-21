# V3 持久拓扑命名修复 — 工作交接文档

> 最后更新: 2026-07-21 Phase 14 完成
> 仓库: WYZAAACCC/text2cad_improve (main 分支)
> 最新 commit: 1d72ad5 (Phase 9-12) + 未提交的 Phase 14 修复

---

## 一、项目背景

Text-to-CAD 系统的持久拓扑命名 V3 升级。目标是让 CAD 模型的每个面在操作序列中拥有**跨重建稳定的身份**，支持实体在操作间正确累积、继承、修改和删除，而非每个阶段重新命名。

### 关键文件路径

```
e:\text_to_cad_improve\auto_detection_process\
├── docs\
│   └── text2cad_persistent_topology_v3_repair_guide.md  ← 修复指导文档（已校对）
├── integrations\engineering_tools\src\seekflow_engineering_tools\generative_cad\
│   ├── topology\          ← V3 拓扑命名核心（~20 文件）
│   │   ├── ids.py         ← gct3_ PID 生成
│   │   ├── models.py      ← TopologyEntityRecord, TopologyDelta, 枚举
│   │   ├── registry.py    ← TopologyRegistry (中央身份权威)
│   │   ├── transaction.py ← TopologyTransaction (原子提交)
│   │   ├── semantic_naming.py ← name_*_faces() + build_entity_records_from_delta()
│   │   ├── shape_binding.py   ← ShapeBindingService + build_operation_input_snapshot()
│   │   ├── history_wrappers.py ← history_aware_* OCCT 包装器
│   │   ├── kernel_identity.py  ← IdentityTransferPolicy (8维决策引擎)
│   │   ├── design_identity.py  ← DesignIdentity, FeatureIdentityReconciler
│   │   ├── cae_bridge.py       ← CAE preflight gate
│   │   └── persistence.py      ← sidecar 读写 + coverage 报告
│   ├── dialects\
│   │   ├── sketch_profile\handlers.py  ← revolve/extrude
│   │   ├── composition\handlers.py     ← boolean/pattern/transform
│   │   ├── axisymmetric\handlers.py
│   │   └── sketch_extrude\handlers.py
│   ├── pipeline\run.py     ← 主编排器
│   ├── runtime\context.py  ← RuntimeContext
│   └── authoring\raw_assembler.py ← IR 组装
├── tests\generative_cad\topology_v3\
│   ├── test_baseline_defects.py  ← 21 个基线测试 (Phase 0)
│   └── (20+ 其他测试文件)
├── turbine_disc\
│   ├── verify_v3_sequence_deep.py  ← 逐阶段验证脚本
│   └── v3_sequence_deep_report_phase14.json
└── app\text-to-cad\server\output\
    └── v3_final_20260721_045319\  ← 最新测试数据
```

### Conda 环境
```
.conda\python.exe  (Python 3.11.9, CadQuery 2.7.0 + OCP)
```

---

## 二、已完成工作总览 (Phase 0-14)

### Phase 0: 失败基线测试
- 新增 `test_baseline_defects.py` (21 测试)，将当前缺陷冻结
- 全部 PASS（冻结缺陷），修复后转为 FAIL

### Phase 1: 身份上下文 + V3 Record 不变量
- `design_identity.py`: 新增 `DesignIdentityContext`
- `semantic_naming.py`: `build_entity_records_from_delta()` 填充 `identity_descriptor`/`lifecycle`/`binding_state`/`proof_class`
- `context.py`: 新增 `design_identity_context` 字段
- `registry.py`: `apply_identity_decisions()` 补充 V3 字段
- `ids.py`: `verify_descriptor_key_consistency()`, strict ordinal 拒绝 (TOPOLOGY_STRICT_V3 门控)
- `models.py`: 新增 `TopologyTimelineEvent`

### Phase 2: Revolve/Extrude 单一路径 V3
- 所有 4 处 `make_persistent_id_v2()` → `_make_compact_key()`
- 删除 "guaranteed semantic naming" 双重注册块

### Phase 3: Transform/Place 身份保持
- 新增 `_register_transform_topology_preservation()` — 面匹配算法
- handle_translate/rotate/place 三个调用点

### Phase 4: Pattern 拓扑事件
- 新增 `_record_pattern_topology_event()`

### Phase 5: Boolean 猜测映射删除 (关键)
- 删除 `mod_i % len` / `pop(0)` / `ancestor_pids[:1]` / `except Exception: pass`

### Phase 6: Timeline + Geometry binding
- `transaction.py`: commit 前验证 geometry bindings
- `context.py`: `record_topology_event()` helper

### Phase 7: CAE strict resolution
- `cae_bridge.py`: 优先使用 `resolve_strict()`

### Phase 8: 回归验证
- 190 passed, 12 baseline FAIL

### Phase 9: FeatureIdentity 链
- `pipeline/run.py`: 构建 `DesignIdentityContext`
- 4 个 dialect 调用点传递 `feature_uid` 到 `_make_compact_key()`

### Phase 10: Source Snapshot 基础设施
- `shape_binding.py`: 新增 `build_operation_input_snapshot()`
- `history_wrappers.py`: `history_aware_boolean_cut()` 接受 PID-keyed 输入
- `composition/handlers.py`: Boolean handler 构建 source snapshot

### Phase 11: 接入 IdentityTransferPolicy
- `composition/handlers.py`: Boolean 路径调用 `IdentityTransferPolicy.decide()` → `apply_identity_decisions()`
- `registry.py`: `apply_identity_decisions()` 设置 `owner_body_handle_id`

### Phase 12: Timeline + Coverage
- Boolean 事件使用 `record_topology_event()` (自动捕获 entities_before/after)
- `persistence.py`: 新增 `write_topology_coverage_report()`

### Phase 14 (未提交): Descriptor 缺口修复 + HashCode Bug + apply_identity_decisions 去重
- 4 个 dialect 站点 + `_reconstruct_descriptor()` 导入
- 3 个 registry 站点: 不再创建 occurrence-keyed 重复 record，改为仅更新已有 record
- `shape_binding.py`: `_compute_shape_content_hash` HashCode fallback
- 测试更新: `test_generated_from_tool_registers_new_entity` → `test_generated_from_tool_records_evidence_on_source`

### Git 提交历史
```
1d72ad5 feat(topology): V3 Phase 9-12 — wire kernel identity, feature_uid, source snapshot
473d31f feat(topology): V3 Phase 0-8 — persistent topology naming repair
```

**Phase 14 改动尚未提交！** (shape_binding.py, sketch_profile, axisymmetric, sketch_extrude, registry.py, test_kernel_identity_layering.py)

---

## 三、当前测试状态

```
181 passed (回归测试)
12 FAIL (基线测试 — 这些是检测到已修复缺陷的测试)
1 warning (geometry binding 非致命警告)
```

### 12 个 FAIL 的基线测试（= 已修复的缺陷）
1-3. lifecycle/binding_state/proof_class 未在 dialects 引用 (Phase 1-2)
4. apply_identity_decisions 未在 dialects 引用 (Phase 11)
5. build_entity_records_has_no_descriptor (Phase 1)
6. all_records_have_v3_fields_none (Phase 1)
7-8. V2 writer 仍在使用 (Phase 2)
9-11. mod_i_modulo_len / pop_zero / ancestor_pids_slice (Phase 5)
12. revolv_records_have_no_descriptor (Phase 1)
13. star_lineage_present (Phase 5 — 但当前运行中 lineage 全空，测试检查旧 sidecar 数据)

### 仍然 PASS 的基线测试（= 未修复 / 设计上不适用）
- test_node_rename_changes_pids (语义命名内部调用点未传 feature_uid)
- test_place_transform_no_topology_event (间接调用模式)
- test_pattern_no_topology_event (同上)
- test_exception_pass_in_boolean_topology (其他 handler 路径)
- 等

---

## 四、最新验证结果 (Phase 14 运行)

使用 `v3_final_20260721_045319` 涡轮盘数据运行完整管线：

```
Pipeline: PASS (96.3s)
3079 entities, 3 producers

逐阶段:
  Seq 0: revolve_disc → 12 entities
  Seq 1: extrude_cutter → 52 new, 12 survive (64 total)
  Seq 2: place → 0 new, all 64 survive
  Seq 3: boolean_cut → 3015 new, 64 survive (3079 total)

Phase 14 Sidecar:
  - Descriptor 覆盖率: 3079/3079 (100%) ✅
  - Lifecycle 覆盖率: 3079/3079 (100%) ✅
  - Generation 分布: 全部为 0 ❌
  - Ancestor 链接: 0/3079 ❌
  - Descendant 链接: 0/3079 ❌
  - 星形 lineage: 无 ✅
  - feature_stable_id: 全部 = producer_node_id ❌
```

---

## 五、三个未解决问题及根因

### 问题 1: Lineage DAG 为空 — **架构缺失**

`build_entity_records_from_delta()` 创建所有 record 时 `ancestor_ids=[]`（默认值）。Phase 5 删除了 `ancestor_pids[:1]` 假 lineage，但从未建立真实的 lineage 替代。

`apply_identity_decisions()` 仅处理 split/merge 的 lineage 链接，普通 generated/modified 实体的 ancestor/descendant 关系在整个系统中没有任何代码负责生成。

**修复方向**：需要在 Boolean 拓扑路径中，根据 OCCT history（哪个 source PID 产生了哪个 result）建立 ancestry 关系。`Generated(source_face)` 的结果面应该把 source PID 作为 ancestor。

### 问题 2: Generation 全部为 0 — **代码 Bug ×2**

**Bug A — body handle 不匹配**：
`build_operation_input_snapshot()` 用 `owner_body_handle_id` 匹配实体。revolve 实体 handle 是 `solid:disc:n_revolve_disc:body`，但 Boolean handler 构造的 target_handle 是 `solid:disc:{node.inputs[0].producer_node}:body`。`node.inputs[0].producer_node` 是 place 节点的 ID（不是 revolve 节点），导致 snapshot 找不到实体，PID-keyed history 无数据，Phase 11 的 generation++ 无法执行。

Place handler 的 `_register_transform_topology_preservation()` 应该更新 `owner_body_handle_id`，但**只在实体有 `current_locator` 时更新**。如果 revolve 走的是 semantic fallback 路径（无 locator），更新就跳过。

**Bug B — 总是创建新 record**：
`build_entity_records_from_delta()` 总是 `generation=0`。Boolean 将 modified 面当作**新实体**创建，而非更新已有实体。当 source_ids 中包含已有 PID 时（modified 关系），应该找到已有 record 并使 `generation += 1`，而不是创建新 record。

**修复方向**：
- Bug A：修正 Boolean handler 的 target_handle 构造，或让 snapshot 函数用更灵活的方式匹配实体（如按 producer_node_id 而非 body_handle_id）
- Bug B：在 `build_entity_records_from_delta()` 中，对于 `relation="modified"` 的情况，更新已有 record 而非创建新的

### 问题 3: feature_stable_id = producer_node_id — **部分实现**

`_reconstruct_descriptor()` 不接受 `feature_uid` 参数，直接使用 `producer_node_id` 作为 `feature_stable_id`。Phase 9 修复了 4 个 dialect 直接调用点，但 `build_entity_records_from_delta()` → `_reconstruct_descriptor()` 这条路径被遗漏。

Boolean 的 3015 个实体全部经过此路径创建，所以全部使用 `producer_node_id`。

**修复方向**：
- `_reconstruct_descriptor()` 增加 `feature_uid` 参数
- `build_entity_records_from_delta()` 从 delta 元数据或 context 获取 `feature_uid`
- 将 `DesignIdentityContext` 传递到 delta 构建链中

---

## 六、关键设计决策记录

1. **`_make_compact_key()` 保持返回 `str`** (25 个调用点，不改返回类型)
2. **descriptor 重推导**：`_reconstruct_descriptor()` 从已有参数重新计算，不改变调用链
3. **严格模式门控**：ordinal token 拒绝通过 `TOPOLOGY_STRICT_V3` 环境变量控制
4. **`apply_identity_decisions()` = 更新已有 record**：record 创建是 delta 路径职责
5. **HashCode fallback**：OCP 对象无 `HashCode` 时回退到 Python `id()`

---

## 七、测试命令速查

```bash
# 快速回归 (不含慢速 turbine disc 管线)
cd e:/text_to_cad_improve/auto_detection_process
.conda/python.exe -m pytest integrations/engineering_tools/tests/generative_cad/topology_v3/ -q --tb=short --ignore=test_baseline_defects.py

# 基线测试 (快速部分)
.conda/python.exe -m pytest test_baseline_defects.py -v -k "not (star_lineage or overshadow)"

# V2 writer 检查
grep -r "make_persistent_id_v2" integrations/engineering_tools/src/.../dialects/ --include="*.py"

# 涡轮盘深度验证
.conda/python.exe turbine_disc/verify_v3_sequence_deep.py

# 读取最新 sidecar
.conda/python.exe -c "import json; sc=json.load(open('app/text-to-cad/server/output/v3_final_20260721_045319/output.topology.json')); ..."
```

---

## 八、未提交的 Phase 14 改动清单

以下文件有未提交的修改（Phase 14 descriptor 缺口修复 + HashCode bug + apply_identity_decisions 去重）：

1. `topology/shape_binding.py` — `_compute_shape_content_hash` HashCode→id() fallback
2. `topology/registry.py` — `apply_identity_decisions()` generated_new_identity/generated_from_tool/merge 不再创建新 record
3. `dialects/sketch_profile/handlers.py` — 2 处 `_reconstruct_descriptor` import + descriptor 填充
4. `dialects/axisymmetric/handlers.py` — 同上 1 处
5. `dialects/sketch_extrude/handlers.py` — 同上 1 处
6. `tests/.../test_kernel_identity_layering.py` — `test_generated_from_tool_registers_new_entity` 更新为 `test_generated_from_tool_records_evidence_on_source`
