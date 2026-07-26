# OCAF 原生拓扑命名 — 实施状态

> 创建日期: 2026-07-25
> 最后更新: 2026-07-26
> 基线 SHA: `b68beedce3f1e96fd095c20b92653e70cae19653`
> 执行依据: `Text-to-CAD_OCAF原生持久化拓扑命名_系统实施指导书_v3.0.md`

---

## 环境

```
Python:     3.11.9 (Anaconda)
CadQuery:   2.7.0
OCP:        7.8.1.1
OS:         Windows 11 Home China 10.0.22631
虚拟环境:   .\.conda\
```

---

## 阶段进度

### PR-0: 冻结诊断与回归基线 ✅ 已完成

- 27/27 smoke 测试通过
- 覆盖: UTF-8 路径 (ASCII + 中文), Tag 100 Schema, TNaming 跨进程, 原子发布

### PR-1: Compat + Schema + Document Core ✅ 已完成

- DesignRoot 固定 Tag 100, ext_utf8(), Retrieve(), Atomic publish
- 修复: 空标签持久化、OCP 析构崩溃、Windows 文件锁、IsKind() API

### PR-2: Live History 与 CaptureSession ✅ 已完成

- 重写 models.py: Live/Audit 分离, ProofClass, validate() 契约
- 重写 capture_session.py: 删除全局 staging, 直接接受 LiveEvolutionBatch
- 修改 tracked_ops/*: 收集真实 TopoDS_Shape Handle
- 26 个新测试全部通过

### PR-3: Boolean + Writer ✅ 已完成

- 状态: ✅ 完成
- 开始: 2026-07-26
- 完成: 2026-07-26

#### 修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `topology/ocaf/writer.py` | 重写 | TopologyNamingWriter: 正确 TNaming 语义, 删除内部事务, 固定 Tag, fail-closed |

#### API 验证 (OCP 7.8.1.1)

| TNaming_Builder 方法 | 签名 | 状态 |
|---------------------|------|------|
| `Generated(new)` | 单参数 | ✅ |
| `Generated(old, new)` | 双参数 | ✅ |
| `Modify(old, new)` | 双参数 | ✅ |
| `Delete(old)` | 单参数 | ✅ |

#### 验收项

- [x] PRIMITIVE → Generated(new_shape)
- [x] GENERATED → Generated(old_shape, new_shape) 支持 1→N
- [x] MODIFIED → Modify(old_shape, new_shape)
- [x] DELETED → Delete(old_shape)
- [x] Writer 不开启内部 transaction
- [x] 异常 fail-closed（rel.validate() + 异常传播）
- [x] 不再使用 NewChild()（FindChild(FIXED_TAG, True)）
- [x] Relation label 使用固定 Tag schema (1001+)

#### 新增测试 (1 文件, 9 测试)

`tests/generative_cad/topology/ocaf/test_writer_correctness.py`:
- T_W4: Writer 不管理 transaction (2 tests)
- T_W5: PRIMITIVE → Generated(new) (2 tests, 含跨进程)
- T_W1: Boolean CUT → write_batch (2 tests)
- T_W6: Fail-closed (1 test)
- T_W2/W3: Relation integrity (2 tests)

#### 测试结果

```
PR-3 新测试:      9/9 ✅
PR-2 测试:       26/26 ✅
PR-0 smoke:      27/27 ✅
---
OCAF 全部:       62/62 ✅
现有回归:        19/20 ✅ (1 已有问题)
```

#### 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| GENERATED/MODIFIED 区别 | Generated 用 `Generated(old,new)`, MODIFIED 用 `Modify(old,new)` | OCP 7.8.1.1 两者均可用, 语义分离 |
| 1→N 实现 | 每个 new_shape 创建独立 child label | 支持 split 场景, 每个生成面有独立 TNaming |
| 固定 Tag | RELATION_TAG_BASE=1001, per-relation tag + per-shape sub-tag | FindChild 稳定, 不依赖 NewChild() 顺序 |
| 事务管理 | Writer 纯写入, 事务由 Revision Session 管理 | §3.3 要求 |

---

## 测试基础设施

- `tests/generative_cad/topology/ocaf/conftest.py`: 共享 fixtures (ascii_tmpdir, chinese_tmpdir, xbf_path_ascii, xbf_path_chinese)
- 所有 OCAF 测试: `pytest tests/generative_cad/topology/ocaf/ -v`

---

## 阻塞项

（无）

---

## 降级项

（无）

---

## 下一步：PR-4 (Selection/Solve)

按照 `系统实施指导书_v3.0.md` §13 执行:

- 新增原生 Selection Service
- 旧 selector 降级为 heuristic candidate
- 加 Semantic Contract

验收:
- 创建时精确选择 FACE
- 跨进程 Retrieve + Solve
- UNIQUE/SET/DELETED/AMBIGUOUS/UNRESOLVED 分类正确
- required selection 不允许 heuristic 自动兜底

**PR-3 门禁已通过。可以进入 PR-4。**
