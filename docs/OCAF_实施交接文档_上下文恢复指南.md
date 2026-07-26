# OCAF 原生持久化拓扑命名 — 实施交接文档 v3.0

> 日期: 2026-07-26
> 用途: 上下文重置后恢复工作状态
> 当前进度: v5.0 PR-A~PR-G 全部完成，198 tests 全通过

---

## 1. 你必须首先读取的文件

| 顺序 | 文件 | 用途 |
|------|------|------|
| 1 | `docs/Text-to-CAD_OCAF原生持久化拓扑命名_下一阶段实施指导书_v5.0.md` | 实施规范——所有工作的执行依据 |
| 2 | `docs/OCAF_完整诊断测试报告_v5.0.md` | **最新** 198 tests 完整状态 |
| 3 | `docs/OCAF_OCP_API限制与已知问题_v1.md` | 13 个 OCP 7.8.1.1 API 限制（部分已解除） |
| 4 | `docs/OCAF_DoD_审计报告_v1.md` | Definition of Done 逐条对照 |
| 5 | `docs/OCAF_项目状态与审查文档_v1.md` | 项目状态概览 |

---

## 2. 环境信息

```
Python:     3.11.9 (Anaconda)
CadQuery:   2.7.0
OCP:        7.8.1.1
OCCT:       7.8.1 (原生 C++ 库)
OS:         Windows 11 Home China 10.0.22631
工作目录:    e:\text_to_cad_improve\auto_detection_process\
虚拟环境:    .\.conda\
Python 路径: .\.conda\python.exe
Git Remote:  text2cad → https://github.com/WYZAAACCC/text2cad_improve.git
测试命令:    cd integrations/engineering_tools && ..\..\.conda\python.exe -m pytest tests/generative_cad/topology/ocaf/ --ignore=tests/.../test_tnaming_roundtrip.py -v
```

---

## 3. 当前完成状态

### v5.0 7 PR 全部完成

| PR | 内容 | 状态 | 测试数 |
|----|------|------|--------|
| PR-A | Index v2 + safe reader + validate exception | ✅ | +16 |
| PR-B | Pipeline order + TopologyRunConfig + verify worker | ✅ | +13 |
| PR-C | RevisionCore + Modify T2 + lineage metadata | ✅ | +4 |
| PR-D | Policy/Contract read + CAE kind + Pattern Fuse history | ✅ | +7 |
| PR-E | Entity dedup + semantics + Solve Worker | ✅ | +6 |
| PR-F | CAE Gate + Pipeline wiring | ✅ | +5 |
| PR-G | T3/T5/T6/T7/T8 scenarios | ✅ | +16 |

### 测试状态

```
198 passed, 0 failed (excluding 2 known-fragile tnaming_roundtrip)
```

---

## 4. OCP API 限制

### 已解除的误判

- ~~`TDataStd_AsciiString.Get_s()` 不存在~~ → `attr.Get()` 实例方法可用 (PR-A 验证)
- ~~Policy/Contract 读取永久受阻~~ → `compat.read_ascii_string()` 可用 (PR-D)
- ~~CAE entity kind 无法检查~~ → `_classify_shape_kind(ShapeType())` (PR-D)
- ~~Pattern Fuse history 缺失~~ → 已补全 Modified/IsRemoved (PR-D)

### 真正的永久限制

1. `TNaming_Selector.Solve()` 在面删除后 ACCESS VIOLATION
2. TNaming destructor crash (子进程退出)
3. `app.Retrieve()` 在垃圾数据上 ACCESS VIOLATION
4. `TNaming_Selector.Select()` 空文档 ACCESS VIOLATION
5. Face 级 UNIQUE Solve 不精确 (body 级 Modify 返回 Compound)
6. `TopoDS_Shape.HashCode` 可能崩溃
7. Windows OCAF 文件句柄阻止 `os.replace`

---

## 5. 未完成的受阻项目

| 项目 | 阻塞原因 |
|------|---------|
| T4 Delete Solve | OCP ACCESS VIOLATION — 无法修复 |
| T12 E2E G-CAD Pipeline | 需要完整 IR 管线 |
| Face 级 UNIQUE Solve | OCP body 级 Modify 限制 |
| Immutable Revision Bundle | 需要 HEAD.json (设计完成，未实施) |
| Atomic publish | Windows OCAF 文件句柄 |
| 乐观并发控制 | 需要 HEAD.json |

---

## 6. 下一步建议

1. **OCP 升级后**: 重试 T4 Delete Solve、Face 级 UNIQUE
2. **IR 管线就绪后**: T12 E2E G-CAD Pipeline
3. **可立即做**: Immutable Revision Bundle 目录结构 (无阻塞)
4. **可立即做**: 乐观并发控制 (HEAD.json + parent conflict)

---

## 7. 关键代码坐标

| 文件 | 关键内容 |
|------|---------|
| `topology/ocaf/compat.py` | `read_ascii_string`, `read_integer` (safe attr readers, Null guard) |
| `topology/ocaf/models.py` | LiveEvolutionRelation, TopologyRunConfig, RevisionRecord, SemanticContract.area_range |
| `topology/ocaf/schema.py` | DESIGN_ROOT_TAG=100, TagPath, Index v2 子标签, Metadata 常量 |
| `topology/ocaf/label_index.py` | StableLabelIndex v2 (fail-closed, 6 counters, get_existing, allocate_relation) |
| `topology/ocaf/repository.py` | OcafRepository.create/open/save_temp/publish |
| `topology/ocaf/document.py` | OcafDocumentSession, set/get_lineage_metadata, write_revision_record, get_current_result_shape |
| `topology/ocaf/writer.py` | write_feature_result (Generated/Modify), write_batch(previous_result=), _relation_tag (Index first) |
| `topology/ocaf/selection_service.py` | explode_entities (IsSame dedup), validate_semantics (area_range), _read_policy/_read_contract (real) |
| `topology/ocaf/cae_preflight.py` | _classify_shape_kind, proof gate, entity kind gate |
| `topology/ocaf/verify_worker.py` | verify_xbf() → VerifyResult (subprocess crash isolation) |
| `topology/ocaf/solve_worker.py` | solve_in_subprocess() → SolveWorkerResult |
| `pipeline/run.py` | _run_ocaf_write_and_save (correct order + CAE preflight) |
| `runtime/context.py` | topology_mode, enable_topology_capture, capture_session |

---

## 8. 核心设计约束

1. ❌ 不使用 `doc.Main().NewChild()` — 使用 `FindChild(TAG, True)`
2. ❌ 不使用 `app.Open(path, doc)` — 使用 `app.Retrieve(folder, name, True)`
3. ❌ 使用不存在 `Get_s()` — 使用 `compat.read_ascii_string/read_integer` (attr.Get())
4. ❌ 不使用 face/edge index 作为持久身份
5. ❌ Writer 不管理事务 — 纯写入
6. ✅ 空标签必须附加属性 (TDataStd_Name) 才能持久化
7. ✅ Solve 前必须调用 `collect_tnaming_labels()`
8. ✅ safe reader 必须检查 `label.IsNull()` (防 ACCESS VIOLATION)
9. ✅ validate() 用 `raise` 不用 `assert`
10. ✅ `load_from_ocaf()` 必须 fail-closed (不吞异常)

---

## 9. 开始工作的检查清单

1. 读取 `OCAF_完整诊断测试报告_v5.0.md` 了解最新状态
2. 读取 `Text-to-CAD_OCAF原生持久化拓扑命名_下一阶段实施指导书_v5.0.md`
3. 确认环境: `..\..\.conda\python.exe -c "import cadquery; print('ok')"`
4. 运行测试: `pytest tests/generative_cad/topology/ocaf/ --ignore=...test_tnaming_roundtrip.py -v`
5. 确认 198 tests 全部通过
6. 查看 §5 了解阻塞项, §6 选择下一步工作
