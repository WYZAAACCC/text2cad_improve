# GCAD 持久化拓扑命名 — 项目状态文档

> **日期**: 2026-07-19
> **分支**: main
> **最后提交**: 2849b9f — feat: GCAD Persistent Topological Naming — full implementation
> **远程**: https://github.com/WYZAAACCC/seekflow-engineering
> **测试**: 108 passed, 0 failed

---

## 1. 做了什么

在 `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/` 下新增 `topology/` 包（15 个模块），实现了完整的 **持久化拓扑命名系统**，解决了原系统中 `face_index`/`edge_index` 在参数变化后漂移的问题。

### 核心架构

```
PersistentTopoId (稳定身份，与 B-Rep 枚举分离)
    │
TopologyRegistry (中央身份权威，管理实体生命周期)
    │
├── semantic_naming.py (确定性语义命名: box, cylinder, extrude, revolve, hole...)
├── history_wrappers.py (OCP 内核历史适配: Generated/Modified/IsDeleted)
├── fingerprint.py (量化几何指纹: compute_face_fingerprint)
├── contracts.py (TopologyContract: 声明每个 operation 产生哪些语义面)
├── policies.py (ResolutionQuality: CAE 需要 EXACT, debug 允许 fingerprint)
├── matcher.py (约束匹配器: provenance + type + adjacency 过滤)
├── cae_bridge.py (NamedTopologySet → FEA preflight gate)
├── cad_adapters.py (SolidWorks/NX/STEP topology adapter interfaces)
├── kernel_validators.py (接入 validation_kernel, 构建时自动运行)
├── persistence.py (topology sidecar 读写, SHA256 校验)
└── validation.py (拓扑验证规则)
```

### Handler 集成 (已集成 7 个 handler)

全部使用 **side-channel 模式**（handler 内部直接调用 `ctx.topology_registry`，不改返回类型）：

| 方言 | Handler | 拓扑生产 | 命名函数 |
|---|---|---|---|
| `sketch_extrude` | `extrude_rectangle` | ✅ 6 entities | `name_extrude_faces()` |
| `sketch_extrude` | `cut_hole` | ✅ 7 entities (3 active + 4 deleted) | `name_hole_faces()` |
| `sketch_profile` | `extrude_profile` | ✅ 52+ entities | `name_extrude_faces()` |
| `sketch_profile` | `revolve_profile` | ✅ 16 entities | `name_revolve_faces()` |
| `axisymmetric` | `revolve_profile` | ✅ 3 entities | `name_revolve_faces()` |
| `composition` | `boolean_union` | ✅ per-op | `name_boolean_faces()` |
| `composition` | `boolean_cut` | ✅ 3015 entities (turbine disk) | `name_boolean_faces()` |

### Side-channel 模式 (集成模板)

```python
# 在 handler 的 return 之前调用:
_try_produce_xxx_topology(node=node, ctx=ctx, solid=solid, ...)

# helper 函数:
def _try_produce_xxx_topology(*, node, ctx, solid, ...):
    try:
        from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
            build_entity_records_from_delta, name_xxx_faces,
        )
    except ImportError:
        return  # 拓扑模块不可用则静默跳过
    try:
        delta = name_xxx_faces(solid, document_id=..., component_id=..., producer_node_id=...)
        records = build_entity_records_from_delta(delta, document_id=...)
        for rec in records:
            ctx.topology_registry.register_entity(rec)
        ctx.topology_registry.apply_delta(delta)
    except Exception as exc:
        ctx.topology_warnings.append({"node_id": node.id, "error": str(exc)})
```

---

## 2. 文件结构

### 新增: `topology/` 包 (15 文件)

```
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/
├── __init__.py           # 公开导出 (~30 symbols)
├── ids.py                # PersistentTopoId (compact 格式: gct:v1:...)
├── models.py             # TopologyEntityRecord, TopologyDelta, TopologyRelation, TopologyResolution, NamedTopologySet
├── registry.py           # TopologyRegistry (注册/解析/delta 应用/快照/完整性检查)
├── persistence.py        # write_topology_sidecar / read_topology_sidecar
├── fingerprint.py        # FaceFingerprint, EdgeFingerprint, compute_face_fingerprint()
├── semantic_naming.py    # name_box_faces, name_cylinder_faces, name_extrude_faces, name_revolve_faces,
│                         # name_hole_faces, name_fillet_faces, name_chamfer_faces, name_shell_faces,
│                         # name_loft_faces, name_sweep_faces, name_boolean_faces,
│                         # build_entity_records_from_delta, extract_sketch_element_ids
├── contracts.py          # TopologyContract, TopologyOutputRole, 预定义契约 (EXTRUDE/REVOLVE/HOLE/BOOLEAN/FILLET/CHAMFER/SHELL/LOFT/SWEEP/HELIX)
├── history_wrappers.py   # history_aware_extrude/revolve/fillet/chamfer/shell/loft/sweep/boolean_fuse/boolean_cut
│                         # + KernelHistoryAdapter, HistoryAwareShapeResult, capability probe
├── policies.py           # ResolutionQuality, ConsumerPolicy, get_consumer_policy()
├── matcher.py            # ConstrainedTopologyMatcher, MatchConstraint, MatchWeights
├── cae_bridge.py         # CaePreflightResult, cae_preflight_gate(), resolve_named_set_to_faces()
├── cad_adapters.py       # TopologyStepExporter, SolidWorksTopologyAdapter, NXTopologyAdapter, CrossBackendTopologyProof
├── kernel_validators.py  # validate_topology_contracts(), validate_topology_references() (接入 validation_kernel)
└── validation.py         # validate_topology_contract/reference/runtime_integrity/artifact_proof
```

### 修改的现有文件 (12 个)

| 文件 | 修改 |
|---|---|
| `runtime/handles.py` | FaceHandle/EdgeHandle 增加 `persistent_topology_id`, `semantic_role`, `generation`, `resolution_status` |
| `runtime/context.py` | RuntimeContext 增加 `topology_registry`, `topology_events`, `topology_warnings`, `topology_validation` |
| `runtime/cache.py` | 缓存条目包装为 `{"result": ..., "topology_registry_fragment": None}` |
| `dialects/results.py` | OperationResult 增加可选 `topology_delta: TopologyDelta \| None` |
| `dialects/executor.py` | `_apply_topology_delta_if_present()` — 在 geometry validation 后应用 delta |
| `dialects/operation.py` | OperationSpec 增加 `topology_contract: object \| None` |
| `dialects/sketch_extrude/handlers.py` | `_try_produce_extrude_topology()` + `_try_produce_hole_topology()` + handler 调用 |
| `dialects/sketch_profile/handlers.py` | `_try_produce_extrude_profile_topology()` + `_try_produce_revolve_profile_topology()` + handler 调用 |
| `dialects/axisymmetric/handlers.py` | `_try_produce_axisymmetric_revolve_topology()` + handler 调用 |
| `dialects/composition/handlers.py` | `_finish_boolean_op()` + `_try_produce_boolean_topology()` + 6 处替换 |
| `dialects/sketch_profile/params.py` | 5 个 sketch element params 增加可选 `element_id` + `semantic_role` |
| `validation_kernel/legacy_adapter.py` | 注册 `core.topology.contract` + `core.topology.reference` 规则 |
| `validation_kernel/stages.py` | 4 个拓扑验证阶段 + TOPOLOGY_CONTRACT 加入 CANONICAL_BARRIER_GROUPS |

### 测试 (8 文件, 108 tests)

```
tests/generative_cad/topology_baseline/
├── __init__.py
├── test_topology_baseline.py   # Phase 1: 25 tests (ids, registry, models, sidecar, box/cylinder naming)
├── test_topology_phase2.py     # Phase 2: 31 tests (contracts, history wrappers, extrude/revolve, policies, matcher, validation)
├── test_topology_phase3.py     # Phase 3: 11 tests (boolean history, hole naming, handler integration, split/merge)
├── test_topology_phase4.py     # Phase 4: 10 tests (fillet/chamfer/shell, contracts)
├── test_topology_phase5.py     # Phase 5: 11 tests (fingerprint computation, loft/sweep, contracts)
├── test_topology_phase6.py     # Phase 6:  8 tests (CAE bridge, preflight gate, NamedTopologySet resolution)
└── test_topology_phase7.py     # Phase 7: 12 tests (STEP/SW/NX adapters, CrossBackendProof)
```

### E2E 测试脚本 (2 个)

```
turbine_disc/
├── run_e2e_topology_test.py    # 简单 block+hole (2 nodes) — 验证 extrude_rectangle + cut_hole topology
└── run_e2e_turbine_disk.py     # 完整涡轮盘 (18 nodes) — 验证 3083 entities, 15.1MB STEP
```

---

## 3. E2E 验证结果

### 涡轮盘 (b572661c219c4952 IR, 18 nodes)

| 操作 | 实体数 | 说明 |
|---|---|---|
| `n_revolve_disc` (sketch_profile.revolve_profile) | 16 | 盘体 |
| `n_extrude_cutter` (sketch_profile.extrude_profile) | 68 | 枞树槽 cutter |
| `n_bool_cut_all` (composition.boolean_cut) | **3083** | 60 槽切割结果 |

- **STEP**: 15.1 MB (与参考 b572661c 完全一致)
- **Pipeline**: ok=True, ~30s

### Block+Hole (最小 IR, 2 nodes)

| 操作 | 实体数 |
|---|---|
| `extrude_rectangle` | 6 (2 caps + 4 sides) |
| `cut_hole` | 13 (9 active: hole faces + 4 deleted: tool faces) |

---

## 4. 当前未覆盖的操作

以下 handler 尚未集成拓扑生产（可以后续加入）：

| 方言 | Handler | 原因 |
|---|---|---|
| `sketch_profile` | `add_polyline`, `close_profile`, `fillet_sketch` | 草图元素 — 不直接产生 solid |
| `sketch_extrude` | `cut_rectangular_pocket`, `add_rib`, `apply_safe_fillet`, `apply_safe_chamfer` | 可仿照 cut_hole 模式集成 |
| `axisymmetric` | `cut_center_bore`, `cut_annular_groove`, `cut_rim_slot_pattern` 等 | 可仿照 cut_hole 模式集成 |
| `shell_housing` | `shell_body`, `hollow_body` | `name_shell_faces()` 已就绪 |
| `loft_sweep` | `loft_sections`, `sweep_profile`, `helix_sweep` | `name_loft_faces()`/`name_sweep_faces()` 已就绪 |
| `composition` | `circular_pattern_component`, `translate_solid`, `rotate_solid` | 阵列/变换操作 |

---

## 5. 关键技术决策

### 为什么用 side-channel 而非 executor path

Handler 直接调用 `ctx.topology_registry.register_entity()` + `apply_delta()`，而非通过 `OperationResult.topology_delta` 返回。

**原因**：
- 不改 handler 返回类型（保持 `dict[str, str]` 兼容）
- 不改 OperationSpec 的 `handler_kind`
- 拓扑失败不阻止构建（non-fatal warning）
- pattern 简单一致：`_try_produce_xxx_topology()` helper

### 为什么跳过部分 handler

- **boolean_union**: 5 个返回点，3 层降级。用 `_finish_boolean_op()` wrapper 统一处理。
- **fillet/chamfer**: OCP wrapper 已就绪，但 CadQuery `body.fillet(r)` 不暴露单边历史，handler 修改风险高。

### Python 环境

- **项目 conda**: `e:/text_to_cad_improve/auto_detection_process/.conda/python.exe` (Python 3.11.9)
- **CadQuery**: 2.7.0 (通过 conda)
- **OCP**: 完整 history API (BRepPrimAPI, BRepAlgoAPI, BRepFilletAPI, BRepOffsetAPI)
- **安装**: `pip install -e integrations/engineering_tools`

### 测试运行

```bash
# 使用项目 conda Python
cd e:/text_to_cad_improve/auto_detection_process
.conda/python.exe -m pip install -e integrations/engineering_tools
.conda/python.exe -m pytest integrations/engineering_tools/tests/generative_cad/topology_baseline/ -v

# E2E 测试
.conda/python.exe turbine_disc/run_e2e_topology_test.py        # 简单 block+hole
.conda/python.exe turbine_disc/run_e2e_turbine_disk.py         # 完整涡轮盘
```

---

## 6. 后续可做的工作

### 短期 (低风险)
1. **集成 sketch_extrude 的 fillet/chamfer** — `name_fillet_faces()`/`name_chamfer_faces()` 已就绪
2. **集成 shell_housing** — `name_shell_faces()` 已就绪
3. **集成 loft_sweep** — `name_loft_faces()`/`name_sweep_faces()` 已就绪
4. **集成 axisymmetric 其余操作** — cut_center_bore, cut_annular_groove 等

### 中期 (中风险)
5. **OperationSpec topology_contract 链接** — 将 `contracts.py` 中的预定义契约连接到 dialect 的 OperationSpec 实例（当前契约存在但未链接，导致 TOPOLOGY_CONTRACT_MISSING warnings）
6. **topology sidecar 自动生成** — 在 pipeline/run.py 中调用 `write_topology_sidecar()`
7. **CAE bridge 实际集成** — 将 `cae_preflight_gate()` 接入 fea_pipeline.py

### 长期 (高风险/需外部环境)
8. **OCP history-aware handler 升级** — 将关键 handler 从 CadQuery 高层 API 迁移到 OCP history wrapper
9. **SolidWorks/NX 真实 adapter 测试** — 当前 adapter 是接口契约，需要 SW/NX 环境实际调用
10. **fingerprint-based fallback 匹配** — `compute_face_fingerprint()` 已就绪，需要配合 constrained matcher 实际匹配

---

## 7. 关键文件速查

| 用途 | 路径 |
|---|---|
| 拓扑 ID 定义 | `topology/ids.py` |
| 拓扑注册表 | `topology/registry.py` |
| 语义命名函数 | `topology/semantic_naming.py` |
| OCP 历史 wrapper | `topology/history_wrappers.py` |
| Handler 集成参考 | `dialects/sketch_extrude/handlers.py` (cut_hole 模式) |
| Side-channel 模板 | 见本文档 §1 "Side-channel 模式" |
| 合约定义 | `topology/contracts.py` |
| CAE bridge | `topology/cae_bridge.py` |
| 最新涡轮盘 IR | `app/text-to-cad/server/output/b572661c219c4952/` |
| E2E 测试脚本 | `turbine_disc/run_e2e_turbine_disk.py` |
| 全部测试 | `tests/generative_cad/topology_baseline/` |
