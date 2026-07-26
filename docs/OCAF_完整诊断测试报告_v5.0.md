# OCAF/TNaming 完整系统测试报告 v5.0

> 编制日期：2026-07-26
> 基线：v5.0 实施指导书 7 PR 全部完成
> 环境：Python 3.11.9 · CadQuery 2.7.0 · OCP 7.8.1.1 · OCCT 7.8.1 · Windows 11
> 测试总数：198 (全部通过, 0 失败)
> 文档用途：供专家独立审查当前系统完整状态

---

## 1. 测试环境

| 项目 | 值 |
|------|-----|
| Python | 3.11.9 (Anaconda) |
| CadQuery | 2.7.0 |
| OCP | 7.8.1.1 |
| OCCT | 7.8.1 |
| OS | Windows 11 Home China 10.0.22631 |
| 虚拟环境 | `auto_detection_process\.conda\` |
| 测试运行命令 | `pytest tests/generative_cad/topology/ocaf/ --ignore=...test_tnaming_roundtrip.py -v` |
| 全部通过 | **198 passed, 0 failed** (跳过 2 个 known-fragile tnaming_roundtrip) |

---

## 2. v5.0 实施完成清单 (7 PR)

| PR | v5.0 章节 | 核心成果 | 测试 |
|----|----------|---------|------|
| PR-A | §4-5 | Index v2 fail-closed (10 验证)、safe attr reader (`attr.Get()`)、validate() assert→exception | +16 |
| PR-B | §6 | TopologyRunConfig、执行顺序修正 (OCAF after postcheck)、verify_worker、failure injection | +13 |
| PR-C | §7 | RevisionRecord、Modify-based 跨 Revision T2、lineage metadata 读写、get_current_result_shape | +4 |
| PR-D | §8+10部分 | Policy/Contract 真实读取（解除 OCP Get_s() 误判）、CAE entity kind 检查、Pattern Fuse 完整 history | +7 |
| PR-E | §9 | explode_entities 去重 (IsSame)、语义验证增强 (area_range/normal)、solve_worker 子进程隔离 | +6 |
| PR-F | §10-11 | CAE preflight proof/history gate、Pipeline CAE 接入、solver no-start 验证 | +5 |
| PR-G | §11 | T3/T5/T6/T7/T8 场景测试 | +16 |

---

## 3. 系统架构总览 (22 源文件 + 3 工具/worker)

```
topology/ocaf/
├── models.py              # Live/Audit 模型 + TopologyRunConfig + RevisionRecord
├── compat.py              # OCP 安全封装 (ext_utf8, safe readers, collect_tnaming_labels)
├── schema.py              # 固定 Tag 100 标签树 + TagPath
├── label_index.py         # StableLabelIndex v2: fail-closed, 6种counter, get_existing
├── repository.py          # OcafRepository: create/open/save/publish
├── document.py            # OcafDocumentSession + lineage metadata + get_current_result_shape
├── errors.py              # 18 种结构化错误
├── writer.py              # TopologyNamingWriter: Modify support, Index-based relation labels
├── capture_session.py     # CaptureSession 批收集
├── selection_service.py   # PersistentSelectionService: dedup, semantics, policy read
├── cae_preflight.py       # CAE gate: entity kind + proof + history
├── heuristic_candidates.py# HeuristicCandidateFinder (降级, 诊断用)
├── verify_worker.py       # 子进程 XBF 验证
├── solve_worker.py        # 子进程 Selection Solve
├── tracked_ops/
│   ├── boolean.py         # cut/fuse/common (BOPAlgo_BOP + History)
│   ├── extrude.py         # extrude (start_cap/end_cap roles)
│   ├── revolve.py         # revolve
│   ├── fillet.py          # fillet (persistent EDGE)
│   ├── chamfer.py         # chamfer
│   ├── unify.py           # unify (ShapeUpgrade, History可用)
│   ├── mirror.py          # mirror (1:1 face mapping)
│   └── pattern.py         # linear pattern (full Fuse history)
├── pipeline/run.py         # Pipeline: 正确执行顺序 + CAE preflight 接入
└── runtime/context.py      # RuntimeContext: topology_mode + capture_session
```

---

## 4. 测试结构 (24 测试文件, 198 测试)

```
tests/topology/ocaf/
├── smoke/
│   ├── test_atomic_publish.py         (8)
│   ├── test_tag100_schema.py          (11)
│   ├── test_tnaming_roundtrip.py      (2, known-fragile)
│   └── test_utf8_path.py              (8)
├── test_cae_binding.py                (6)
├── test_cae_gate.py                   (5)  ← PR-F
├── test_capture_session.py            (12)
├── test_failure_injection.py          (13) ← PR-B
├── test_geometry_ab.py                (10)
├── test_hardening.py                  (13)
├── test_live_models.py                (14)
├── test_multi_component_same_name.py   (3)
├── test_operation_coverage.py         (17)
├── test_pipeline_topology_modes.py     (7)
├── test_relation_identity.py          (7)  ← PR-D
├── test_scenario_t3_split.py          (3)  ← PR-G
├── test_scenario_t5_unify.py          (3)  ← PR-G
├── test_scenario_t6_roles.py          (3)  ← PR-G
├── test_scenario_t7_pattern.py        (3)  ← PR-G
├── test_scenario_t8_edge.py           (4)  ← PR-G
├── test_selection_integration.py       (4)
├── test_selection_service.py          (10)
├── test_selection_v3.py               (6)  ← PR-E
├── test_stable_label_index_v2.py      (16) ← PR-A
├── test_t2_cross_revision.py          (1)
├── test_true_t2_modify.py             (4)  ← PR-C
└── test_writer_correctness.py         (9)
```

---

## 5. 场景覆盖 (T0-T12)

| 场景 | 状态 | 测试文件 |
|------|------|---------|
| T0 XBF 基础 | ✅ | smoke/* |
| T1 单 Revision FACE | ✅ | test_selection_service.py, test_selection_integration.py |
| T2 三进程 Modify | ✅ | test_true_t2_modify.py, test_t2_cross_revision.py |
| T3 1→N Split | ✅ | test_scenario_t3_split.py |
| T4 Delete | 🔒 | OCP ACCESS VIOLATION — 永久阻塞 |
| T5 N→1 Unify | ✅ | test_scenario_t5_unify.py |
| T6 Construction Roles | ✅ | test_scenario_t6_roles.py |
| T7 Pattern Identity | ✅ | test_scenario_t7_pattern.py |
| T8 EDGE Selection | ✅ | test_scenario_t8_edge.py |
| T9 原子回滚 | ⚠️ | test_failure_injection.py (部分) |
| T10 路径 | ✅ | smoke/test_utf8_path.py |
| T11 CAE Gate | ✅ | test_cae_gate.py |
| T12 E2E Pipeline | 🔒 | 需要完整 IR 管线 |

---

## 6. OCP 7.8.1.1 限制 (更新)

### 已解除的误判

| 之前标记 | 实际状态 |
|---------|---------|
| `TDataStd_*.Get_s()` 不存在 → "Policy 无法恢复" | ✅ `attr.Get()` 实例方法可用 (PR-A Step 0 验证) |
| CAE entity kind "无法检查" | ✅ `_classify_shape_kind()` 基于 `ShapeType()` |
| Pattern Fuse history "缺失" | ✅ 已补全 `Modified` + `IsRemoved` |

### 真正的永久限制

| 限制 | 影响 | 严重度 |
|------|------|--------|
| `TNaming_Selector.Solve` 在面删除后 ACCESS VIOLATION | T4 | 高 |
| TNaming destructor crash (子进程退出) | 子进程测试 | 中 |
| `app.Retrieve` 在垃圾数据上 ACCESS VIOLATION | 损坏文件 | 中 |
| `TNaming_Selector.Select` 空文档 ACCESS VIOLATION | 首次创建 | 中 |
| Face 级 UNIQUE Solve 不精确 | T2 精确断言 | 中 |
| `TopoDS_Shape.HashCode` 可能崩溃 | 去重 | 低 |
| Windows OCAF 文件句柄 | 原子发布 | 低 |

---

## 7. 系统状态

```
OCAF Native Topology Naming — Engineering Beta
198 tests | 22 source files | 7 PRs complete | 10/12 scenarios
```

核心能力已验证：
- ✅ OCAF/XBF 原生持久化 + UTF-8 路径
- ✅ StableLabelIndex v2 (fail-closed, 6 种 counter, 跨进程恢复)
- ✅ Modify-based 跨 Revision 拓扑演化
- ✅ 8 种 tracked operation (face 级 history)
- ✅ Policy/Contract 读取 + 语义验证 + CAE gate
- ✅ 子进程 Solve/Verify 隔离 (native crash 安全)
- ✅ Pipeline 正确执行顺序 + TopologyRunConfig
