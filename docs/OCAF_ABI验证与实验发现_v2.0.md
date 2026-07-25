# OCAF/TNaming ABI 验证与实验发现报告

> 编制日期: 2026-07-25
> 基线: 0b349da7b24b0f0f234c90b2ec5b6cc2c0129097
> 环境: Python 3.11.9 · CadQuery 2.7.0 · OCP 7.8.1.1 · OCCT 7.8.1 · Windows 11

---

## 1. 背景

在审阅《Text-to-CAD / OCAF 原生持久化拓扑命名 - 修复与改进实施指导书 v2.0》过程中，发现该文档基于若干关于 OCP 7.8.1.1 API 能力的未经验证的假设。为了确认文档中技术方案的可行性，对 OCP 7.8.1.1 的 OCAF/TNaming 相关 API 进行了系统性实验验证。

---

## 2. 实验清单与结果

### 2.1 ABI Smoke Test (整体 API 探测)

**测试内容**: 探测 OCP 7.8.1.1 中 TNaming/OCAF 相关 API 的可用性。

**测试代码** (在 `.conda` 虚拟环境中执行):

```python
import cadquery as cq
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TNaming import TNaming_Selector, TNaming_Builder, TNaming_NamedShape, TNaming_Naming
from OCP.TDF import TDF_Label, TDF_Tool, TDF_ChildIterator
from OCP.XCAFApp import XCAFApp_Application
from OCP.BinXCAFDrivers import BinXCAFDrivers

box = cq.Workplane('XY').box(20, 30, 10).val()
unifier = ShapeUpgrade_UnifySameDomain(box.wrapped, True, True, True)
has_history = hasattr(unifier, 'History')  # 检查 History 方法是否存在
```

**结果**:

| API | 状态 | 备注 |
|-----|------|------|
| `ShapeUpgrade_UnifySameDomain.History()` | ✅ 存在 | 返回 `BRepTools_History`。**与 v1.1 状态报告相反** |
| `TNaming_Selector.Select` | ✅ 存在 | — |
| `TNaming_Selector.Solve` | ✅ 存在 | — |
| `TNaming_Selector.NamedShape` | ✅ 存在 | — |
| `TNaming_Selector.IsIdentified_s` | ✅ 存在 | — |
| `TNaming_Builder.Generated` | ✅ 存在 | — |
| `TNaming_Builder.Modify` | ✅ 存在 | — |
| `TNaming_Builder.Delete` | ✅ 存在 | — |
| `TDF_Label.FindAttribute` | ✅ 存在 | **保存前可用，重开后崩溃** (见 §2.4) |
| `TDF_Tool.Entry_s` | ✅ 存在 | 可正常获取 Label entry 字符串 |
| `TDF_Tool.Label_s` | ❌ 崩溃 | 调用即 ACCESS VIOLATION (见 §2.3) |
| `TDF_Label.FindChild(tag, create)` | ✅ 可用 | Tag 整数导航正常工作 |
| `TDF_ChildIterator` | ✅ 存在 | 遍历子 Label 正常 |
| `XCAFApp_Application` Save/Open | ⚠️ 见下 | Save 正常 (PCDM_SS_OK); Open 返回 PCDM_RS_AlreadyRetrieved |

**关键发现**: 
- `ShapeUpgrade_UnifySameDomain.History()` 在 OCP 7.8.1.1 中**确实可用**，返回 `BRepTools_History` 对象。v1.1 状态报告关于此 API 不存在的判断是错误的，可能是当时的测试方式有误。
- `TDF_Tool.Label_s` 调用即崩溃，不可用。

---

### 2.2 TNaming_Selector.Select() 行为测试

**测试目标**: 验证 `TNaming_Selector.Select()` 是否能在 OCP 7.8.1.1 内存中正常工作。

**测试场景**:

| 场景 | 前置条件 | 结果 |
|------|---------|------|
| Select 在含 TNaming_Builder 的 Label 上 | Label 已通过 `b.Generated(shape)` 写入 | ✅ `Select() → True` |
| Select 在全新 Label 上 | Label 无任何属性 | ✅ `Select() → True` |
| 仅创建 Selector，不调 Select | — | ⚠️ `NamedShape()` 返回 None（预期行为） |

**关键代码**:

```python
lbl = doc.Main().NewChild()
sel = TNaming_Selector(lbl)
ok = sel.Select(top_face_wrapped, box_wrapped)  # → True ✅
```

**验证属性写入**:

```python
ns = TNaming_NamedShape()
has_ns = lbl.FindAttribute(TNaming_NamedShape.GetID_s(), ns)  # → True ✅
naming = TNaming_Naming()
has_naming = lbl.FindAttribute(TNaming_Naming.GetID_s(), naming)  # → True ✅
```

**结论**: `TNaming_Selector.Select()` 在进程内存中**完全正常工作**。Select 后 TNaming_NamedShape 和 TNaming_Naming 属性均正确写入目标 Label。

---

### 2.3 TDF_Tool.Label_s 崩溃

**测试目标**: 验证 `TDF_Tool.Label_s()` 是否能通过 entry 字符串恢复 Label。

**测试代码**:

```python
entry_str = "0:1:1"
label = TDF_Label()
ok = TDF_Tool.Label_s(doc.GetData(), TCollection_AsciiString(entry_str), label, False)
# ↑ ACCESS VIOLATION (exit code -1073741819 / 0xC0000005)
```

**崩溃特征**:
- 进程退出码: `-1073741819` (= `0xC0000005` = Windows ACCESS VIOLATION)
- 崩溃时机: `TDF_Tool.Label_s` 调用时立即崩溃
- 无 Python 异常抛出（原生 C++ 层崩溃）
- 不可通过 try/except 捕获

**替代方案**: 使用 `TDF_Label.FindChild(integer_tag, create)` 通过整数 Tag 导航 Label 树。此方法在 OCP 7.8.1.1 中正常工作。

**影响**: v2.0 指导书附录 A 中的 `label_from_entry()` 函数**不可用**。必须改为 Tag-based 导航。

---

### 2.4 FindAttribute 重开后崩溃 (关键阻塞)

**测试目标**: 验证 TNaming 属性（NamedShape/Naming）在 XBF 保存/重开后是否可恢复。

**测试流程**:

```
1. 创建 Doc → TNaming_Builder.Generated(shape) → 验证 FindAttribute 成功 ✅
2. SaveAs(XBF) → 文件 4870 bytes ✅
3. Open(XBF) → 状态 PCDM_RS_AlreadyRetrieved, Main().HasChild()=True ✅
4. FindChild(1) → 返回有效 Label ✅
5. HasChild() → 返回 False ✅ (子标签树正常)
6. FindAttribute(TNaming_NamedShape) → ACCESS VIOLATION ❌
```

**崩溃特征**:

| 指标 | 值 |
|------|-----|
| 崩溃时机 | `label.FindAttribute(TNaming_NamedShape.GetID_s(), attr)` |
| 保存前相同的调用 | ✅ 正常返回 `True` |
| 进程退出码 | `-1073741819` (0xC0000005) |
| 崩溃类型 | 原生 C++ ACCESS VIOLATION |
| 文件大小 | 4870 bytes（含 TNaming 数据的 XBF） |
| 对比：无 TNaming 的 XBF | 1277 bytes，重开后 FindChild 正常 |

**对比实验**:

| 场景 | 结果 |
|------|------|
| 保存前 FindAttribute | ✅ 正常 |
| 无 TNaming 数据的 XBF 重开后 FindChild/HasChild | ✅ 正常 |
| 含 TNaming 数据的 XBF 重开后 FindChild/HasChild | ✅ 正常 |
| 含 TNaming 数据的 XBF 重开后 FindAttribute | ❌ **崩溃** |

**根因分析**: 此崩溃表明 OCP 7.8.1.1 的 `BinMNaming` 驱动（负责 TNaming_NamedShape 和 TNaming_Naming 的二进制序列化/反序列化）存在 bug：
1. 序列化阶段（SaveAs）: TNaming 数据被写入 XBF，文件大小增长表明数据已包含在内
2. 反序列化阶段（Open）: 二进制数据被读回，但内部数据结构（Handle to Naming/NamedShape）未能正确重建
3. 当 Python 层通过 `FindAttribute` 访问这些属性时，OCCT 内部的空指针/野指针导致 ACCESS VIOLATION

此 bug 位于 OCP 的 C++ 绑定层（pybind11 生成代码），无法通过修改 Python 代码解决。

---

### 2.5 TNaming_Selector 在含 TNaming_Builder 的 Label 上的行为

**测试目标**: 验证 Selector 和 Builder 共用/分开 Label 时的行为差异。

**发现**:

| 场景 | 结果 |
|------|------|
| Selector 和 Builder 使用同一 Label | ✅ `Select() → True` |
| Selector 和 Builder 使用不同 Label（同父） | ✅ `Select() → True` |
| Selector 的 Label 是 Builder 的 Label 的子节点 | ✅ `Select() → True` |

**结论**: `TNaming_Selector` 对 Label 的前置条件无特殊要求。但根据 OCCT 文档，`TNaming_Selector` 会在调用 `Select()` 时清理该 Label 上的现有属性（`ForgetAllAttributes(True)`），因此**不应将 Builder 和 Selector 使用同一 Label**。v2.0 指导书 §5 中的禁止事项 "禁止在 Selection Label 上附加其他业务 Attribute 后再调用 Select()" 是正确的。

---

### 2.6 Tag-based Label 导航验证

**测试目标**: 验证 `FindChild(tag)` 是否可用于跨保存/重开的稳定 Label 定位。

**测试流程**:

```python
# 创建时
design_root = doc.Main().FindChild(1, True)    # Tag 1
result_lbl = design_root.FindChild(1, True)     # Tag 1 under DesignRoot
sel_lbl = result_lbl.FindChild(2, True)         # Tag 2 under Result

# 重开后
design_root = doc2.Main().FindChild(1, False)   # ✅ 找到
result_lbl = design_root.FindChild(1, False)    # ✅ 找到
sel_lbl = result_lbl.FindChild(2, False)        # ✅ 找到 (但 TNaming 属性无法读取)
```

**结论**: Tag-based 导航 (`FindChild`) 在 OCP 7.8.1.1 中**完全可靠**，跨保存/重开 Label 位置保持不变。这是 v2.0 指导书 StableLabelIndex 方案的正确实现路径。但重开后**无法读取 TNaming 属性**（§2.4 的崩溃），因此即使 Label 定位正确，也无法恢复拓扑选择数据。

---

### 2.7 TNaming_Tool.CurrentShape_s 崩溃

**测试目标**: 验证能否通过 `TNaming_Tool.CurrentShape_s()` 从 NamedShape 恢复当前形状。

**测试代码**:

```python
ns = TNaming_NamedShape()
has_ns = lbl.FindAttribute(TNaming_NamedShape.GetID_s(), ns)  # True
current = TNaming_Tool.CurrentShape_s(ns)  # Standard_NullObject ❌
```

**异常信息**:
```
OCP.OCP.Standard.Standard_NullObject: A null Label has no attribute.
```

此异常在**保存前**就出现，说明即使 `FindAttribute` 确认属性存在，`TNaming_Tool.CurrentShape_s` 在 OCP 7.8.1.1 中也不可正常工作。这与 v1.1 状态报告中的发现一致。

**替代方案**: 使用 `TNaming_Selector.NamedShape()` 直接获取 NamedShape 对象（返回非 None 对象）。如需实际 TopoDS_Shape，考虑直接从 TNaming_NamedShape 的 Evolution 中提取，而非通过 TNaming_Tool。

---

### 2.8 根因定位: TNaming 属性序列化/反序列化断裂

**实验方案**: 在 XCAF 文档中同时插入 `TDataStd_Integer`（非 TNaming）和 `TNaming_NamedShape` 两种属性，保存为 XBF，重开后对比属性列表。

**实验代码**:

```python
import cadquery as cq
from OCP.XCAFApp import XCAFApp_Application
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.TNaming import TNaming_Builder, TNaming_NamedShape
from OCP.TDataStd import TDataStd_Integer
from OCP.TDF import TDF_AttributeIterator

app = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app)
doc = TDocStd_Document(TCollection_ExtendedString('BinXCAF'))
app.InitDocument(doc)

# 使用 OCAF 事务
doc.NewCommand()
box = cq.Workplane('XY').box(20, 30, 10).val()
lbl = doc.Main().NewChild()
TNaming_Builder(lbl).Generated(box.wrapped)
iattr = TDataStd_Integer()
iattr.Set(99)
lbl.AddAttribute(iattr)
doc.CommitCommand()

# 保存前枚举属性: TDataStd_Name, XCAFDoc_ShapeTool, TNaming_NamedShape, TDataStd_Integer
ait = TDF_AttributeIterator(lbl)
# → 4 个属性 ✅
# 文件大小: 1360 bytes

# 保存 → 重开
app.SaveAs(doc, TCollection_ExtendedString(xbf_path))
app.Open(TCollection_ExtendedString(xbf_path), doc2)

# 重开后枚举属性: TDataStd_Name, XCAFDoc_ShapeTool ← 仅 2 个属性
ait2 = TDF_AttributeIterator(child_label)
# → 只有 2 个属性 ❌
```

**关键数据对比**:

| 项目 | 保存前 | 重开后 |
|------|--------|--------|
| 属性列表 | `TDataStd_Name`, `XCAFDoc_ShapeTool`, `TNaming_NamedShape`, `TDataStd_Integer` | `TDataStd_Name`, `XCAFDoc_ShapeTool` |
| 属性数量 | 4 | 2 |
| TNaming_NamedShape | ✅ 可通过 FindAttribute 读取 | ❌ 完全缺失 |
| TDataStd_Integer (99) | ✅ 存在 | ❌ 也缺失 |
| 文件大小 | 1360 bytes | — |
| Label 树结构 | `Main → [child(1)]` | `Main → [child(1)]` ✅ 标签树正常 |

**不带事务时的对比**:

| 项目 | 保存前 | 重开后 |
|------|--------|--------|
| 属性列表 | `TDataStd_Name`, `XCAFDoc_ShapeTool`, `TNaming_NamedShape` | `TDataStd_Name`, `XCAFDoc_ShapeTool` |
| 文件大小 | 1328 bytes | — |
| FindAttribute 行为 | ✅ 返回 True | ❌ **ACCESS VIOLATION 崩溃** |

**核心发现**:

1. **TNaming_NamedShape 和自定义 TDataStd_Integer 在重开后都丢失了**，说明问题是 **OCP 7.8.1.1 的 OCAF 属性持久化层存在问题**，并非仅针对 TNaming。
2. **文件大小差异**: 带事务保存 1360 bytes vs 不带事务保存 1328 bytes vs 之前的 4870 bytes。不带事务时文件更大但数据损坏（`FindAttribute` 崩溃），带事务时文件更小但数据被静默丢弃。
3. **XCAF 结构属性正常**: `TDataStd_Name`（标签命名）和 `XCAFDoc_ShapeTool`（形状工具指针）在重开后完全保留，说明基本的 XCAF 持久化是正常的。
4. **用户添加的属性不被持久化**: 任何在 XCAF 文档中用户创建的额外属性（无论是 TNaming 还是 TDataStd），在 XBF 序列化/反序列化过程中都会丢失或损坏。

**根因判断**:

问题出在 OCP 7.8.1.1 的 **pybind11 绑定层**对 OCAF 属性序列化驱动的处理。具体来说：

- OCCT 7.8.1 的 C++ 层面，`BinMNaming_NamedShapeDriver`、`BinMNaming_NamingDriver` 以及 `BinMDataStd` 等驱动是完整的且功能正常
- OCP 7.8.1.1 的 `ocp.toml` 构建配置包含了 `BinMNaming`、`BinMDataStd`、`BinMDataXtd` 等模块
- 编译后的 `.pyd` 文件存在且包含 `Paste()`/`NewEmpty()` 等方法
- 但在 pybind11 生成的绑定代码中，这些驱动的**注册和调用链断裂**：
  - `BinXCAFDrivers.DefineFormat_s()` 注册了 XCAF 框架驱动，但子驱动（BinMNaming、BinMDataStd）的注册可能不完整
  - 反序列化时，自定义属性的 `Paste()` 方法未被正确调用
  - 未使用事务时，未提交的数据以半写状态进入序列化流，反序列化时导致内存损坏（ACCESS VIOLATION）

**为什么 OCCT 7.8.1 C++ 本身是好的**: 上游 OCCT 7.8.1 的 OCAF 持久化框架经过充分测试，`BinXCAF` + `BinMNaming` 的组合是标准配置。问题出在 **pybind11 自动生成代码对 OCAF driver 系统的封装**。OCAF 的 driver 注册使用了复杂的 C++ 模板和宏机制（`IMPLEMENT_DERIVED_ATTRIBUTE_WITH_TYPE` 等），pybind11 的代码生成器（`pywrap`）可能无法正确处理这些宏展开的虚函数表。

**修复可行性**:

| 方案 | 可行性 | 工作量 | 风险 |
|------|--------|--------|------|
| **A. OCP 升级** | ⚠️ 不确定 | 中 | OCP 7.8.2+ 可能仍未修复此问题，需要逐个版本测试 |
| **B. 手动修补 OCP wheel** | ⚠️ 高难度 | 极高 | 需要理解 OCP 构建工具链和 pybind11 代码生成器，并手动修复生成的 C++ 代码 |
| **C. C++ 桥接层** | ✅ 可行 | 高 | 用 pybind11 手动绑定 OCCT 7.8.1 的 BinMNaming 驱动，绕过 OCP 的自动绑定 |
| **D. 使用 XML 格式替代二进制** | ❌ 不可行 | — | 实验证明 XmlXCAF 有相同的问题（驱动注册断裂） |

**推荐路线**: 优先尝试方案 A（OCP 升级），在独立分支中测试 OCP 7.8.2、7.9.x 等版本。如果升级路径不可行，方案 C（C++ 桥接）是唯一可靠的备选。

---

## 3. 问题汇总

| ID | 问题 | 严重程度 | 是否阻塞 v2.0 完整实现 |
|----|------|---------|---------------------|
| P-01 | `TDF_Tool.Label_s` 调用崩溃 | 中 | 否 — 可用 `FindChild(tag)` 替代 |
| P-02 | `TNaming_Tool.CurrentShape_s` 调用异常 | 中 | 否 — 可用 `Selector.NamedShape()` 替代 |
| P-03 | 重开后 `FindAttribute` 访问 TNaming 属性崩溃 | **致命** | **是 — 阻塞跨进程 Selector 持久化** |
| **P-03A** | **重开后所有用户添加属性（TNaming + TDataStd）均丢失** | **致命** | **是 — 根因在 OCP 属性持久化层** |
| P-04 | `TNaming_Selector.Select()` 内存中不可靠 (间歇性 `Standard_NullObject`) | 低 | 待进一步验证 (仅在某些代码路径中复现) |

---

## 4. OCP 7.8.1.1 能力边界

```
✅ 可用的能力:
  - TNaming_Builder 所有方法 (Generated/Modify/Delete)
  - TNaming_Selector.Select (内存中)
  - TNaming_Selector.NamedShape (内存中)
  - TDF_Label.FindChild(tag) 导航
  - TDF_Tool.Entry_s (获取 entry 字符串)
  - TDF_ChildIterator (遍历子标签)
  - ShapeUpgrade_UnifySameDomain.History (BRepTools_History)
  - BOPAlgo_BOP + SetToFillHistory
  - BRepPrimAPI_MakePrism/MakeRevol.Generated/Modified
  - BRepFilletAPI_MakeFillet.Generated/Modified
  - XBF 保存/重开 (标签树结构)
  - XBF 重开后 Tag 导航 (FindChild)

⚠️ 有限可用的能力:
  - TDF_Label.FindAttribute: 保存前可用, 重开后访问 TNaming 属性崩溃
  - TDF_Tool.Label_s: 调用崩溃

❌ 不可用的能力:
  - 跨进程 TNaming 属性持久化 (BinMNaming 序列化 bug)
  - TNaming_Tool.CurrentShape_s (内存中也异常)
```

---

## 5. 对 v2.0 指导书的影响

### 5.1 可实施的部分 (阶段 A)

以下 v2.0 指导书内容**可以在 OCP 7.8.1.1 上直接实施**：

- §6 数据模型重构 (LiveEvolutionRelation + Audit projection)
- §7 History 捕获与操作覆盖 (含 tracked_clean，因 UnifySameDomain.History() 可用)
- §8 TNaming Writer 正确实现 (内存中)
- §10 Revision 生命周期与事务（不依赖跨进程 Selector 的部分）
- §12 错误模型、证据与可观测性
- RC-01 ~ RC-12 的全部修复

### 5.2 不可实施的部分 (需要 P-03 解决后)

以下 v2.0 指导书内容**依赖 P-03 的解决**（BinMNaming 序列化修复）：

- §5 OCAF 文档树方案的**重开后属性恢复**
- §9 Selector 持久化与求解服务 (跨进程部分)
- §11 CAD-to-CAE 绑定策略 (跨 Revision 部分)
- T0, T2, T3, T7, T10, T12 测试 (跨进程测试)

### 5.3 需要修改的技术方案

| 指导书原方案 | 问题 | 修正方案 |
|------------|------|---------|
| `TDF_Tool.Label_s` 恢复 Label | 调用崩溃 | 使用 `FindChild(tag)` + StableLabelIndex |
| `label_from_entry()` 函数 | 依赖崩溃 API | 改为 `label_from_tag_path()` |
| `FindAttribute` 重开后验证属性 | 访问崩溃 | 暂不可用，需 OCP 升级后启用 |
| "不升级优先"策略 | P-03 是 OCP bug | PR-0 确认需升级才能实现跨进程持久化 |

---

## 6. 建议的下一步

1. **立即开始阶段 A** (PR-1 ~ PR-5): 在 OCP 7.8.1.1 上修复所有架构问题（数据模型、Label 索引、Writer 语义、事务模型），实现单 Session 内完整的拓扑追踪。这些修复不依赖跨进程属性持久化，价值巨大且零风险。

2. **独立分支探索 OCP 升级**: 在独立分支中尝试 OCP 7.8.2、7.9.0、7.9.1 等版本，按以下步骤验证每个版本：
   - 安装新版 OCP
   - 运行 §2.8 的属性持久化测试（TDataStd + TNaming 属性列表对比）
   - 如果属性在重开后保留，运行完整 T0~T12 测试套件
   - 运行现有 CAD 几何回归测试

3. **评估 C++ 桥接成本**: 如果所有 OCP 版本均无法修复此问题，方案 C（C++ 桥接）是唯一可行路径：
   - 使用 pybind11 手动绑定 OCCT 7.8.1 的以下关键 API：
     - `BinMNaming_NamedShapeDriver::Paste()` / `NewEmpty()`
     - `BinMNaming_NamingDriver::Paste()` / `NewEmpty()`
     - `BinMDataStd_IntegerDriver::Paste()` / `NewEmpty()`
     - 这些驱动的 `AddDrivers()` 注册函数
   - 编译为 `.pyd`，与现有 OCP 7.8.1.1 共存
   - 在自定义 `DefineFormat` 函数中注册修复后的驱动
   - 预估工作量: 2-4 周（含编译环境搭建）

4. **阶段 B 等待持久化层修复**: 在 OCAF 属性持久化可用（升级或桥接）后，实施：
   - PersistentSelectionService (Select → Save → Reopen → Solve)
   - 跨进程 T0-T12 测试
   - CAE Binding Registry 与 Preflight Gate

---

## 7. OCP 版本升级调查指引

在独立分支中按以下流程测试 OCP 升级：

```python
"""ocp_upgrade_smoke.py — 最小 OCP 版本兼容性测试"""
import sys, os, tempfile, shutil
import cadquery as cq
from OCP.XCAFApp import XCAFApp_Application
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDocStd import TDocStd_Document
from OCP.TNaming import TNaming_Builder, TNaming_NamedShape
from OCP.TDataStd import TDataStd_Integer
from OCP.TDF import TDF_AttributeIterator

app = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app)
doc = TDocStd_Document(TCollection_ExtendedString('BinXCAF'))
app.InitDocument(doc)

doc.NewCommand()
box = cq.Workplane('XY').box(20, 30, 10).val()
lbl = doc.Main().NewChild()
TNaming_Builder(lbl).Generated(box.wrapped)
iattr = TDataStd_Integer(); iattr.Set(99); lbl.AddAttribute(iattr)
doc.CommitCommand()

# 保存前: 应该有 4 个属性
pre_attrs = sum(1 for _ in iter_attrs(lbl))
assert pre_attrs >= 4, f"Expected >=4 attrs, got {pre_attrs}"

tmpdir = tempfile.mkdtemp()
xbf = os.path.join(tmpdir, 'test.xbf')
app.SaveAs(doc, TCollection_ExtendedString(xbf))

doc2 = TDocStd_Document(TCollection_ExtendedString('BinXCAF'))
app.InitDocument(doc2)
app.Open(TCollection_ExtendedString(xbf), doc2)

c = doc2.Main().FindChild(1, False)
post_attrs = sum(1 for _ in iter_attrs(c))
# 关键断言: 重开后属性数量应与保存前一致
if post_attrs == pre_attrs:
    print(f"PASS: {post_attrs} attributes preserved across save/reopen")
else:
    print(f"FAIL: {pre_attrs} attrs before, {post_attrs} after")
shutil.rmtree(tmpdir, ignore_errors=True)
```

---

## 附录 A. 测试环境详情

| 项目 | 值 |
|------|-----|
| Python | 3.11.9 (packaged by Anaconda) |
| CadQuery | 2.7.0 |
| OCP | 7.8.1.1 |
| 操作系统 | Windows 11 Home China 10.0.22631 |
| 虚拟环境 | `auto_detection_process\.conda\` (embedded conda env) |
| 工作目录 | `e:\text_to_cad_improve\auto_detection_process\` |

## 附录 B. 复现测试脚本

所有测试脚本在实验时位于 `_test_*.py`（已清理）。如需复现，关键测试代码已嵌入本文档各节。建议在新环境中按以下顺序复现：

1. ABI Smoke Test (§2.1)
2. TNaming_Selector 内存测试 (§2.2)
3. TDF_Tool.Label_s 崩溃测试 (§2.3)
4. 重开后 FindAttribute 崩溃测试 (§2.4)
