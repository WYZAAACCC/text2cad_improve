# OCAF 原生持久化拓扑命名 — 实施交接文档

> 创建日期: 2026-07-25
> 用途: 上下文清除后恢复工作状态，指导后续实施
> 当前进度: 诊断阶段完成，准备进入 PR-0 实施

---

## 1. 你必须首先读取的文件

按优先级排列：

### 必读（架构与方案）

| 顺序 | 文件 | 用途 |
|------|------|------|
| 1 | `docs/Text-to-CAD_OCAF原生持久化拓扑命名_系统实施指导书_v3.0.md` | **实施规范**——所有 PR 的唯一执行依据 |
| 2 | `docs/OCAF_完整诊断测试报告_v3.0.md` | 完整测试历史、代码、原始输出、根因分析 |
| 3 | `docs/OCAF_实施状态报告_v1.1.md` | 初始实施状态和 v1.0 时代的已知问题 |
| 4 | `docs/OCAF_ABI验证与实验发现_v2.0.md` | 早期 ABI 验证（顶部有更新通知） |

### 选读（审查意见，按时间顺序）

| 文件 | 内容 |
|------|------|
| `docs/可能的问题.md` | 第一轮审查：指出 PCDM_RS_AlreadyRetrieved 问题 |
| `docs/测试缺陷.md` | 第二轮审查：指出 Open 输出 Handle 问题 |
| `docs/测试缺陷2.md` | 第三轮审查：指出 NewChild() 返回 XCAF 保留标签 |
| `docs/测试缺陷3,md` | 第四轮审查：指出 Writer Driver 查找假设，建议 START_TYPES + EmptyLabelsSavingMode |
| `docs/测试缺陷4.md` | 第五轮审查：确认突破，指出需验证 TNaming 自身 + UTF-8 构造 |

### 理解当前代码

| 文件 | 用途 |
|------|------|
| `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf/models.py` | 当前数据模型（RC-01: 不存 live Shape） |
| `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf/document.py` | 当前文档管理（RC-03~06: 多个 bug） |
| `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf/writer.py` | 当前 Writer（RC-02: 语义全错） |
| `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf/selectors.py` | 当前 FaceSelector（RC-12: 指纹当权威） |
| `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf/capture_session.py` | 当前 CaptureSession（RC-10: 全局 staging） |
| `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf/compat.py` | 当前兼容层 |
| `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf/tracked_ops/boolean.py` | Boolean tracked op |
| `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf/tracked_ops/extrude.py` | Extrude tracked op |
| `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf/tracked_ops/revolve.py` | Revolve tracked op |
| `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf/tracked_ops/fillet.py` | Fillet tracked op（RC-11: Edge index） |
| `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py` | Pipeline 集成点（RC-06,08,09） |
| `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/context.py` | RuntimeContext（OCAF 字段） |

---

## 2. 环境信息

```
Python:     3.11.9 (packaged by Anaconda)
CadQuery:   2.7.0
OCP:        7.8.1.1
OCCT:       7.8.1 (原生 C++ 库)
OS:         Windows 11 Home China 10.0.22631
工作目录:    e:\text_to_cad_improve\auto_detection_process\
虚拟环境:    .\.conda\
Python 路径: .\.conda\python.exe
Git Remote:  text2cad → https://github.com/WYZAAACCC/text2cad_improve.git
```

**执行所有 Python 命令的方式**:
```powershell
cd e:\text_to_cad_improve\auto_detection_process
.\.conda\python.exe <script.py>
```

---

## 3. 诊断阶段最终结论

经过 10 项诊断测试、5 轮外部审查后确认：

### OCP 7.8.1.1 的 OCAF/TNaming 原生持久化完全正常

**不需要升级 OCP、不需要重写 BinMNaming 驱动、不需要 C++ sidecar。**

此前所有测试失败的三层根因：

| 层 | 症状 | 根因 |
|----|------|------|
| 1 | 同进程 Open 后属性消失 | `SaveAs()` 将文档登记到 Application Session → `Open()` 返回 `PCDM_RS_AlreadyRetrieved` → 文件未实际加载 |
| 2 | 跨进程后标签 NOT FOUND | `tempfile.mkdtemp()` 生成含中文用户名的路径 → `TCollection_ExtendedString(str)` 默认 `isMultiByte=false` → UTF-8 字节被错误复制为 UTF-16 → XBF 保存/读取静默损坏 |
| 3 | `NewChild()` 标签错乱 | `TDF_TagSource` 从 0 开始计数 → 第一次 `NewChild()` 返回已被 XCAF 占用的 Tag 1 (Shapes)、Tag 2 (Colors) |

### TNaming 跨进程验证已通过

```
TNaming_Builder.Generated(box) → Save(ASCII/XBF) → Retrieve → NamedShape 恢复 ✅
TNaming_Selector.Select(face, box) → Save → Retrieve → NamedShape+Naming 全部保留 ✅
TNaming_Tool.CurrentShape_s(realHandle) → 返回有效拓扑, 不崩溃 ✅
```

### 必须遵守的调用约束

1. **路径**: `TCollection_ExtendedString(str(path), True)` — 第二个参数不可省略
2. **文档读取**: `app.Retrieve(folder, name, True)` — 不用 `app.Open(path, doc)`
3. **标签创建**: `FindChild(TAG, True)`, TAG ≥ 100 — 不用 `doc.Main().NewChild()`
4. **属性访问**: `TDF_AttributeIterator` — `FindAttribute` 返回 Restore 壳 (Label 为空)
5. **进程边界**: 跨进程 subprocess 验证 — 不能依赖同进程对象可访问
6. **禁用 API**: `TDF_Tool.Label_s()` 崩溃, `TNaming_Tool.CurrentShape_s(FindAttribute壳)` 异常

---

## 4. 当前任务：PR-0 + PR-1

按照 `系统实施指导书_v3.0.md` §13 执行。

### PR-0: 冻结诊断与回归基线

**新增文件**:
- `tests/topology/ocaf/smoke/` 目录下的测试脚本
- 将诊断测试中已验证通过的用例固化为自动化测试

**必须覆盖的测试**:
1. UTF-8 路径构造 (`TCollection_ExtendedString(str, True)`)
2. 中文路径 SaveAs + Retrieve
3. ASCII 路径 SaveAs + Retrieve
4. Tag 100 标签树创建与恢复
5. TDataStd_Integer 跨进程持久化
6. TNaming_Builder.Generated 跨进程 NamedShape 恢复
7. TNaming_Selector.Select 跨进程 (NamedShape + Naming 恢复)
8. capture-off 几何回归（STEP 体积、面数不变）

**验收**:
- 所有 smoke 测试通过
- 环境版本锁定

### PR-1: Compat + Schema + Document Core

**修改文件**:
- `topology/ocaf/compat.py` — 扩展安全 API
- `topology/ocaf/document.py` — 重写

**新增文件**:
- `topology/ocaf/schema.py` — 固定 Tag 树
- `topology/ocaf/label_index.py` — StableLabelIndex
- `topology/ocaf/repository.py` — OcafRepository (create/retrieve/save/publish)
- `topology/ocaf/errors.py` — 结构化错误类型

**新增测试**:
- `tests/topology/ocaf/test_utf8_path.py`
- `tests/topology/ocaf/test_fixed_schema.py`
- `tests/topology/ocaf/test_atomic_publish.py`
- `tests/topology/ocaf/test_subprocess_retrieve.py`

**关键实现要点**:

```python
# compat.py — 安全路径构造
def ext_utf8(value: str | Path) -> TCollection_ExtendedString:
    return TCollection_ExtendedString(str(value), True)

# compat.py — 安全文档读取
def retrieve_xcaf_document(app, path: Path):
    p = Path(path).resolve()
    doc = app.Retrieve(ext_utf8(p.parent), ext_utf8(p.name), True)
    # 检查 Retrieve 状态
    return doc

# schema.py — 固定 Tag
DESIGN_ROOT_TAG = 100
TAG_METADATA = 1
TAG_COMPONENTS = 2
TAG_SELECTIONS = 3
TAG_ASSEMBLY = 4
TAG_CAE_BINDINGS = 5
TAG_REVISIONS = 6
TAG_STABLE_ID_INDEX = 7

# 创建 DesignRoot
design_root = doc.Main().FindChild(DESIGN_ROOT_TAG, True)

# 重开 DesignRoot
design_root = doc.Main().FindChild(DESIGN_ROOT_TAG, False)
if design_root.IsNull():
    raise OcafSchemaError("Missing DesignRoot tag 100")
```

**禁用模式**（PR-1 结束后代码中不得出现）:
- `doc.Main().NewChild()`
- `app.Open(path, doc)` + `app.InitDocument(doc)` 组合
- `TDF_Tool.Label_s()`
- `TCollection_ExtendedString(str)` 无第二个参数
- `FindAttribute` 结果用于需要真实 Handle 的 API

### 验收门禁 (PR-1 完成后)

```
创建固定 Tag 100
→ 写入 Name / Integer / TNaming_NamedShape / TNaming_Naming
→ 中文临时路径 SaveAs
→ 进程退出
→ Retrieve
→ 固定 TagPath 找回所有内容
→ verifier 通过
→ 原子发布
```

**PR-1 未通过，不得进入 PR-2 (Live History 重构)。**

---

## 5. 实施规则（来自指导书 §1.4，必须遵守）

- 使用 `Faces()[i]`、`Edges()[i]` 作为持久身份 ❌
- 使用 Python `hash()` 生成持久 Tag ❌
- 在 `doc.Main()` 下调用无约束 `NewChild()` ❌
- 使用面积、质心、法向、最近邻作为权威身份 ❌
- 调用 `TDF_Tool.Label_s()` ❌
- 在正式读取链中使用未检查状态的 `app.Open(..., doc)` ❌
- 在异常路径使用 `except Exception: pass` ❌
- 在核心重构 PR 中同时升级 CadQuery/OCP/OCCT ❌
- 不检查 Store/Retrieve 状态 ❌
- 同进程对象可访问当作持久化成功 ❌

---

## 6. 关键参考坐标

| 内容 | 文档位置 |
|------|---------|
| 实施规范 | `系统实施指导书_v3.0.md` |
| 测试报告 | `OCAF_完整诊断测试报告_v3.0.md` |
| 初始状态 | `OCAF_实施状态报告_v1.1.md` |
| 早期 ABI | `OCAF_ABI验证与实验发现_v2.0.md` (顶部有更新通知) |
| v2.0 指导书(原始) | `Text-to-CAD_OCAF原生持久化拓扑命名_修复与改进实施指导书_v2.0.md` |
| v1.0 指导书(原始) | `Text-to-CAD_OCAF持久化拓扑命名_代码Agent实施指导书_v1.0.md` |

---

## 7. 开始工作的检查清单

1. ✅ 读取 `系统实施指导书_v3.0.md`（必读 #1）
2. ✅ 读取 `OCAF_完整诊断测试报告_v3.0.md` 了解测试历史
3. ✅ 确认环境可用: `.\.conda\python.exe -c "import cadquery; print('ok')"`
4. ✅ 确认 git 状态: `git status` (应在 main 分支，工作树干净)
5. ✅ 记录基线 SHA: `git rev-parse HEAD`
6. ✅ 创建实施状态文件: `docs/OCAF_原生拓扑命名_implementation_status.md`
7. ✅ 开始 PR-0: 固化诊断测试为自动化 smoke tests

---

> **最后一个指令**: 开始前先读取 `系统实施指导书_v3.0.md`，它是一切的执行依据。本交接文档是补充，不是替代。
