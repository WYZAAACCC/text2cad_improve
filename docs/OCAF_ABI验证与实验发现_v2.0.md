# OCAF/TNaming ABI 验证与实验发现报告

> ⚠️ **重要更新 (2026-07-25)**: 本文档中关于"跨进程属性持久化不可用"的结论已被后续测试推翻。
> **OCP 7.8.1.1 的 BinXCAF/XmlXCAF 原生持久化完全正常。** 之前测试失败的三层根因:
> 1. `PCDM_RS_AlreadyRetrieved` (同进程 Session 缓存)
> 2. `TCollection_ExtendedString` 中文路径编码 (tempfile.mkdtemp 含中文用户名)
> 3. `NewChild()` 返回 XCAF 保留标签
>
> **完整诊断过程与最终验证见**: `OCAF_完整诊断测试报告_v3.0.md`
>
> ---
>
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

### 2.4 同进程 Open 的实验缺陷与修正

**初始实验记录**（现已确认存在缺陷）:

```
1. SaveAs(XBF) → 文件 4870 bytes ✅
2. 同一进程 Open(XBF) → PCDM_RS_AlreadyRetrieved
3. FindAttribute → ACCESS VIOLATION ❌
```

**缺陷根源**: 

经对照 OCCT 7.8.1 `TDocStd_Application.cxx` 源码确认：
- `SaveAs()` 内部会调用 `theDoc->Open(this)` 将文档注册到 Application Session
- 同一 `XCAFApp_Application` 实例再次 `Open()` 同一路径时，`IsInSession()` 返回 true
- 此时 `Retrieve()` 不会执行，`Open()` 返回 `PCDM_RS_AlreadyRetrieved`
- Python 侧的 `doc2` 仍然是空白文档

即之前实验观察到的"重开后的属性丢失和崩溃"是因为**文件根本没有被重新加载**。

**修正后的跨进程测试**:

使用 `subprocess` 启动独立 Python 进程进行读取，确保 `Open()` 真正从磁盘加载文件：

| 项目 | Writer 进程 | Reader 进程 |
|------|-----------|-----------|
| TDataStd_Integer (42) | ✅ 存在 | ❌ 不存在 |
| TNaming_NamedShape | ✅ 存在 | ❌ 不存在 |
| Selector 子标签 | ✅ `0:1:1:1` | ❌ `FindChild(1) → null` |
| Open 状态 | `PCDM_SS_OK` | **`PCDM_RS_OK`** |
| 文件大小 | 9751 bytes | — |
| 标签树 (Main.FindChild(1)) | ✅ | ✅ 存在但仅含 2 个框架属性 |

**关键结论**:
- 同进程 `Open` 返回 `PCDM_RS_AlreadyRetrieved` 确实意味着文件未加载，之前据此得出的"崩溃"结论存在实验缺陷
- 但跨进程测试（真正 `PCDM_RS_OK` + 新进程）**仍然证实**：用户添加的属性在 XBF 序列化/反序列化后丢失
- 丢失的属性包括 `TDataStd_Integer`（非 TNaming）和 `TNaming_NamedShape`，说明问题不限于 TNaming

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

### 2.7 OCP FindAttribute 输出参数绑定缺陷

**测试目标**: 验证 `TNaming_Tool.CurrentShape_s()` 是否可用。

**原始测试**（存在问题）:

```python
ns = TNaming_NamedShape()
has_ns = lbl.FindAttribute(TNaming_NamedShape.GetID_s(), ns)  # True
current = TNaming_Tool.CurrentShape_s(ns)  # Standard_NullObject ❌
```

**根因分析**: 

OCP 存在已知的 `TDF_Label.FindAttribute` 输出参数绑定缺陷 (参考 OCP issue #55, PR #57)。C++ 签名：

```cpp
bool FindAttribute(const Standard_GUID& id, Handle(TDF_Attribute)& attribute);
```

OCP 的修补方式是通过 `Restore()` 将真实属性内容复制到用户传入的空对象：

```cpp
Handle(TDF_Attribute) dummy_attr;
auto rv = self.FindAttribute(anID, dummy_attr);
anAttribute.Restore(dummy_attr);
return rv;
```

`Restore()` 设计用于事务回滚，不是用于建立完整的 Handle 关系。结果：
- `FindAttribute` 返回 True ✅
- 但 Python 中的 `ns` 是"壳对象"：**`ns.Label().IsNull() == True`**
- `TNaming_Tool.CurrentShape_s(ns)` 内部调用 `ns.Label().FindAttribute(...)`，Label 为空导致 `Standard_NullObject`

**验证**:

| 获取方式 | Label().IsNull() | 结论 |
|---------|-----------------|------|
| `lbl.FindAttribute(GUID, ns)` → `ns` | **True** ← 假 Handle | OCP 补丁返回的是内容复制体 |
| `selector.NamedShape()` → `ns` | **False** ← 真 Handle | 直接返回文档中的真实 Handle |

**修正后的用法**:
- 使用 `TNaming_Selector.NamedShape()` 获取真实 NamedShape Handle（绕过 FindAttribute 的 Restore 问题）
- 使用 `TNaming_Selector` 上的 `Solve()` 方法
- 未来需要返回值式 C++ API 替代所有输出参数式调用

**对 P-02 的修正**: `TNaming_Tool.CurrentShape_s` 本身并非不可用——当传入真实 Handle（如 `selector.NamedShape()` 返回值）时应该可以正常工作。之前观察到的异常根因是 OCP 的 `FindAttribute` 输出绑定缺陷。

---

### 2.8 跨进程属性持久化验证（修正后）

**实验方案**: Writer 进程写入 XBF（含 TDataStd_Integer + TNaming_NamedShape + TNaming_Selector），Reader 进程（独立 `subprocess`）重开并验证。

**方法要点**:
- 使用 `subprocess` 启动独立 Python 进程，确保 OCCT Application Session 隔离
- 使用 `TDF_AttributeIterator` 枚举真实属性（不依赖存在缺陷的 `FindAttribute` 输出绑定）
- 使用 `TNaming_Selector.NamedShape()` 获取真实 Handle（非 Restore 壳对象）

**Writer 进程结果**:

```
文件: 9751 bytes
保存前属性: TDataStd_Name, XCAFDoc_ShapeTool, TNaming_NamedShape, TDataStd_Integer (42)
Selector 标签: 0:1:1:1
selector.NamedShape().Label().IsNull() = False (真实 Handle)
```

**Reader 进程结果** (独立 subprocess):

| 项目 | 结果 |
|------|------|
| `Open()` 状态 | **`PCDM_RS_OK`** ✅ |
| `Main.HasChild()` | True ✅ |
| `Main.FindChild(1)` | 有效标签 ✅ |
| `TDF_AttributeIterator` 枚举 | **仅 TDataStd_Name, XCAFDoc_ShapeTool** ❌ |
| TDataStd_Integer (42) | **丢失** ❌ |
| TNaming_NamedShape | **丢失** ❌ |
| Selector 子标签 (tag 1) | **不存在（IsNull）** ❌ |

**关键结论**:

1. **跨进程 XBF 持久化确实存在问题**——即使使用正确的 `PCDM_RS_OK` + 新进程，用户添加的所有属性（TNaming 和 TDataStd）在重开后均丢失
2. **但之前的同进程测试因 `PCDM_RS_AlreadyRetrieved` 导致文件未被加载**，使得 ACCESS VIOLATION 崩溃现象产生误导——原以为是反序列化内存损坏，实为对空文档访问不存在的属性
3. **BinMNaming 驱动注册问题已被排除**——OCCT 7.8.1 源码显示 `BinXCAFDrivers::DefineFormat()` 内部会调用 `BinMNaming::AddDrivers()`，这些注册是 C++ 原生完成的
4. **根因需要进一步的 Writer-vs-Reader 分离测试**——当前无法判断属性是在序列化（写 XBF）还是反序列化（读 XBF）阶段丢失的

**与"可能的问题.md"文档的对照**:

| 文档主张 | 验证结果 |
|---------|---------|
| §1: 同进程 Open 返回 AlreadyRetrieved 意味着文件未加载 | ✅ **完全正确**——已验证 |
| §1: 属性丢失结论可能是因为检查了空文档 | ⚠️ **部分正确**——同进程测试确实有缺陷，但修正后的跨进程测试仍证实属性丢失 |
| §2: InitDocument 自动添加 XCAF 框架属性解释了为何只剩 2 个 | ✅ **正确** |
| §3: OCP FindAttribute 使用 Restore() 产生假 Handle | ✅ **完全正确**——实验验证了 `Label().IsNull()` 差异 |
| §4: BinMNaming 驱动由 C++ 内部注册，不需要 Python 手动注册 | ✅ **正确**——与 OCCT 源码一致 |
| §5-6: 仓库代码本身有严重问题 | ✅ **正确**——RC-01~RC-12 全部确认 |

**当前 OCP 7.8.1.1 的准确能力边界**:

```
✅ 可用的能力:
  - TNaming_Builder.Generated/Modify/Delete (内存中)
  - TNaming_Selector.Select (内存中)
  - TNaming_Selector.NamedShape (返回真实 Handle, Label 非空)
  - TDF_Label.FindChild(tag) 导航 (跨重开可靠)
  - ShapeUpgrade_UnifySameDomain.History()
  - XBF 保存/重开 (标签树结构保留)
  - XBF 重开后 TDF_AttributeIterator (枚举真实属性)

⚠️ 有限可用的能力:
  - TDF_Label.FindAttribute: 返回 Restore 壳对象, Label 为空 (OCP 已知问题)
  - TDF_Tool.Label_s: 调用崩溃
  - XBF 跨进程: PCDM_RS_OK 可正常打开, 但用户属性丢失

❌ 不可用的能力:
  - 跨进程 TNaming/TDataStd 属性持久化 (属性在 XBF 往返后丢失)
  - 跨进程 Selector 数据持久化 (Selector 标签子树不保留)
```

---

## 3. 问题汇总（修正后）

| ID | 问题 | 严重程度 | 修正后状态 |
|----|------|---------|-----------|
| P-01 | `TDF_Tool.Label_s` 调用崩溃 | 中 | 未变 — 可用 `FindChild(tag)` 替代 |
| P-02 | `TNaming_Tool.CurrentShape_s` 异常 | **已降级** | **根因不是 CurrentShape_s，而是 OCP FindAttribute 输出绑定缺陷**。使用 `selector.NamedShape()` 返回的真实 Handle 应可正常工作 |
| P-03 | 同进程 Open 后 `FindAttribute` 崩溃 | **已重新定性** | **根因是 PCDM_RS_AlreadyRetrieved 导致文件未加载**（同进程测试缺陷）。跨进程测试中 `FindAttribute` 行为待验证 |
| P-04 | 跨进程 XBF 往返后用户属性丢失 | **致命** | **新的核心阻塞问题** — 真正的跨进程测试（PCDM_RS_OK）证实 TDataStd_Integer 和 TNaming_NamedShape 均丢失 |
| P-05 | OCP `FindAttribute` 输出参数绑定缺陷 | 中 | **新发现** — `Restore()` 补丁产生的壳对象 `Label().IsNull()==True`，不能用于需要真实 Handle 的 API |

**"可能的问题.md"文档的贡献**:

该文档对之前实验的批判中有 **4 项完全正确、1 项部分正确、1 项错误**：

| 判断 | 验证 |
|------|------|
| PCDM_RS_AlreadyRetrieved 意味着文件未加载 | ✅ 正确 |
| InitDocument 自动添加的框架属性解释了"只剩2属性" | ✅ 正确 |
| OCP FindAttribute 输出绑定有 Restore 壳问题 | ✅ 正确 |
| BinMNaming 由 C++ 内部注册 | ✅ 正确 |
| 仓库代码本身严重问题 (RC-01~12) | ✅ 正确 |
| "属性丢失可能是因为检查了空文档" | ⚠️ 部分 — 同进程测试确有缺陷，但修正后仍证实丢失 |
| "真正的 OCAF 原生持久化拓扑命名是可以实现的 (不升级)" | ✅ **最终证实正确** — ASCII 路径下 BinXCAF/XmlXCAF 均完全正常。详见 v3.0 报告 §15 |

---

## 4. OCP 7.8.1.1 能力边界（最终版, 经 9 项诊断测试确认）

```
✅ 可用的能力:
  - TNaming_Builder 所有方法 (Generated/Modify/Delete)
  - TNaming_Selector.Select — 写入真实 NamedShape/Naming
  - TNaming_Selector.NamedShape — 返回真实 Handle (Label 非空)
  - TDF_Label.FindChild(tag) 导航 — 跨重开完全可靠
  - TDF_AttributeIterator — 枚举真实属性
  - ShapeUpgrade_UnifySameDomain.History — BRepTools_History
  - BOPAlgo_BOP + SetToFillHistory
  - BRepPrimAPI_MakePrism/MakeRevol.Generated/Modified
  - BRepFilletAPI_MakeFillet.Generated/Modified
  - BinXCAF 跨进程完整持久化 — 标签树+全部用户属性 ✅ (ASCII路径)
  - XmlXCAF 跨进程完整持久化 ✅ (ASCII路径)
  - XBF 跨进程 Open/Retrieve — PCDM_RS_OK 正常

⚠️ 有限可用的能力:
  - TDF_Label.FindAttribute: 返回 Restore() 壳对象, Label().IsNull()==True
  - TDF_Tool.Label_s: 调用崩溃 → 用 FindChild(tag) 替代
  - TCollection_ExtendedString: 不支持中文路径 → 须使用纯 ASCII 路径

❌ 不可用的能力:
  - TNaming_Tool.CurrentShape_s(FindAttribute壳对象) — 因假Handle 的 Label 为空
```

---

## 5. 对 v2.0 指导书的影响（修正后）

### 5.1 可实施的部分 (阶段 A — 不需要升级 OCP)

以下 v2.0 指导书内容**可以在 OCP 7.8.1.1 上直接实施**：

- §6 数据模型重构 (LiveEvolutionRelation + Audit projection) — 需要保存真实 TopoDS_Shape
- §7 History 捕获与操作覆盖 — 含 tracked_clean (UnifySameDomain.History() 可用)
- §8 TNaming Writer 正确实现 — 内存中正确调用 Generated/Modify/Delete
- §10 Revision 生命周期与事务 — 不依赖跨进程 Selector 的部分
- §12 错误模型、证据与可观测性
- RC-01 ~ RC-12 的全部修复
- StableLabelIndex (Tag-based FindChild 导航)
- Lineage Document 架构 (新建/重开统一 DesignRoot)

### 5.2 不可实施的部分 (需要 P-04 解决后)

以下 v2.0 指导书内容**依赖跨进程属性持久化修复**：

- §5 OCAF 文档树的**重开后属性恢复**
- §9 Selector 持久化与求解服务 (跨进程部分)
- §11 CAD-to-CAE 绑定策略 (跨 Revision 部分)
- T0, T2, T3, T7, T10, T12 测试 (跨进程测试)

### 5.3 需要修改的技术方案

| 指导书原方案 | 问题 | 修正方案 |
|------------|------|---------|
| `TDF_Tool.Label_s` 恢复 Label | 调用崩溃 | 使用 `FindChild(tag)` + StableLabelIndex |
| `label_from_entry()` 函数 | 依赖崩溃 API | 改为 `label_from_tag_path()` |
| `FindAttribute` 读取属性 | 返回 Restore 壳对象 | 使用 `TNaming_Selector.NamedShape()` 或 C++ 返回值式 API |
| 不升级 OCP 完成跨进程持久化 | P-04 当前未解决 | 需要进一步 Writer/Reader 分离测试定位确切断裂点 |
| `TNaming_Tool.CurrentShape_s` 不可用 | 实际是 FindAttribute 假 Handle 问题 | 用 `selector.NamedShape()` 获取真实 Handle 后再调用 |

---

## 6. 最终结论与下一步（第三轮修正后）

> **本节的原始内容已被推翻。** 以下是最新结论：

**OCP 7.8.1.1 的 OCAF 原生持久化完全正常。** 无需升级 OCP、无需 C++ sidecar、无需私有 wheel。

1. **立即开始 v2.0 指导书全部 PR 计划** (PR-0 ~ PR-8): 修复应用层问题（数据模型、Label 索引、Writer 语义、事务模型），实施完整跨进程 Selector 持久化、CAE Binding。

2. **遵守 ASCII 路径约束**: 所有 XBF/XML 文件路径使用纯 ASCII

3. **遵守标签创建规范**: `FindChild(TAG, True)`, TAG >= 100，禁用 `doc.Main().NewChild()`

详细诊断过程与验证数据见: `OCAF_完整诊断测试报告_v3.0.md`

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

## 8. 系统诊断测试套件

以下是在发现 §2.4 同进程测试缺陷后，为精确定位问题根源而设计的 6 个诊断测试。所有测试均使用**跨进程**（`subprocess` 启动独立 Python 进程）确保 `Open()` 真正从磁盘加载文件。

### 8.1 核心方法

```python
def reader_subprocess(xbf_path, app_type="xcaf"):
    """在独立子进程中打开 XBF 文件并检查属性."""
    code = f'''
import sys, json
sys.path.insert(0, r"integrations\\engineering_tools\\src")
from OCP.XCAFApp import XCAFApp_Application
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDocStd import TDocStd_Document
from OCP.TDF import TDF_AttributeIterator
app = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app)
doc = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app.InitDocument(doc)
s = app.Open(TCollection_ExtendedString(r"{xbf_path}"), doc)
c = doc.Main().FindChild(1, False)
r = {{"open": str(s)}}
if not c.IsNull():
    attrs = []
    ait = TDF_AttributeIterator(c)
    while ait.More():
        attrs.append(type(ait.Value()).__name__)
        ait.Next()
    r["attrs"] = attrs
print(json.dumps(r))
'''
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30,
        cwd=r"e:\text_to_cad_improve\auto_detection_process",
    )
    return json.loads(r.stdout) if r.stdout and r.returncode == 0 else {"error": r.stderr[:300]}
```

---

### 8.2 诊断测试 1: BinDrivers vs BinXCAF 格式

**测试目标**: 区分问题是否只在 XCAF 层，还是底层 BinDrivers 同样受影响。

**Writer 代码**:

```python
# Test A: Pure TDocStd + BinDrivers format (no XCAF)
from OCP.TDocStd import TDocStd_Application, TDocStd_Document
from OCP.BinDrivers import BinDrivers
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Integer, TDataStd_Name
from OCP.TDF import TDF_AttributeIterator

app_a = TDocStd_Application()
BinDrivers.DefineFormat_s(app_a)
doc_a = TDocStd_Document(TCollection_ExtendedString("BinOcaf"))
app_a.InitDocument(doc_a)

doc_a.NewCommand()
lbl = doc_a.Main().NewChild()
TDataStd_Name.Set_s(lbl, TCollection_ExtendedString("MyLabel"))
iattr = TDataStd_Integer(); iattr.Set(42); lbl.AddAttribute(iattr)
doc_a.CommitCommand()

# 保存前: 2 属性 (TDataStd_Name, TDataStd_Integer)
xbf_a = "test_a.cbf"
app_a.SaveAs(doc_a, TCollection_ExtendedString(xbf_a))

# Test B: BinXCAF + TDataStd_Integer (control)
from OCP.XCAFApp import XCAFApp_Application
from OCP.BinXCAFDrivers import BinXCAFDrivers

app_b = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app_b)
doc_b = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app_b.InitDocument(doc_b)

doc_b.NewCommand()
lbl_b = doc_b.Main().NewChild()
iattr_b = TDataStd_Integer(); iattr_b.Set(42); lbl_b.AddAttribute(iattr_b)
doc_b.CommitCommand()

# 保存前: 3 属性 (TDataStd_Name, XCAFDoc_ShapeTool, TDataStd_Integer)
xbf_b = "test_b.xbf"
app_b.SaveAs(doc_b, TCollection_ExtendedString(xbf_b))
```

**Reader 结果** (独立子进程):

| 测试 | 格式 | 文件大小 | Open状态 | Child找到? | 属性内容 |
|------|------|---------|---------|-----------|---------|
| A | BinOcaf (纯TDocStd) | 437 bytes | PCDM_RS_OK | ❌ child_null | — |
| B | BinXCAF | 1313 bytes | PCDM_RS_OK | ✅ | 仅 TDataStd_Name, XCAFDoc_ShapeTool |

**关键发现**:
- **纯 BinDrivers 格式连标签树都不保留**。`BinDrivers.DefineFormat_s()` 在 OCP 中注册后，SaveAs 产生的文件无法在重开时恢复 Label 层级结构。
- **BinXCAF 保留标签树和 XCAF 框架属性，但 TDataStd_Integer 丢失**。`InitDocument()` 自动添加的 `XCAFDoc_ShapeTool` 和 `TDataStd_Name` 可以恢复，但用户通过 `AddAttribute` 添加的 `TDataStd_Integer` 丢失。

**完整测试脚本**: `_diag1_basic.py`（已清理，代码见上）

---

### 8.3 诊断测试 2: AddAttribute vs Set_s 属性创建方式

**测试目标**: 验证不同的属性创建方式（`AddAttribute` vs `Set_s`）是否影响持久化结果。排除"Set_s（XCAF 框架方法）可以持久化，AddAttribute（普通方法）不能"的假设。

**Writer 代码**:

```python
from OCP.XCAFApp import XCAFApp_Application
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.TCollection import TCollection_ExtendedString, TCollection_AsciiString
from OCP.TDocStd import TDocStd_Document
from OCP.TDataStd import TDataStd_Integer, TDataStd_Real, TDataStd_AsciiString, TDataStd_Name

app = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app)
doc = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app.InitDocument(doc)

doc.NewCommand()
lbl = doc.Main().NewChild()

# 方法 1: Set_s (XCAF 框架方法)
TDataStd_Name.Set_s(lbl, TCollection_ExtendedString("TestLabel"))

# 方法 2: AddAttribute (普通方法) — TDataStd_Integer
iattr = TDataStd_Integer(); iattr.Set(42); lbl.AddAttribute(iattr)

# 方法 3: AddAttribute — TDataStd_Real
rattr = TDataStd_Real(); rattr.Set(3.14); lbl.AddAttribute(rattr)

# 方法 4: Set_s (非 XCAF 框架方法) — TDataStd_AsciiString
sattr = TDataStd_AsciiString.Set_s(lbl, TCollection_AsciiString("hello"))

doc.CommitCommand()
```

**保存前属性枚举** (通过 `TDF_AttributeIterator`):

```
TDataStd_Name, XCAFDoc_ShapeTool, TDataStd_Integer(42), TDataStd_Real(3.14), TDataStd_AsciiString
```

**Reader 结果** (独立子进程, PCDM_RS_OK):

```
TDataStd_Name, XCAFDoc_ShapeTool
```

**关键发现**:

| 属性类型 | 创建方式 | 保存前存在? | 重开后存在? |
|---------|---------|-----------|-----------|
| `TDataStd_Name` | `Set_s` (XCAF框架) | ✅ | ✅ |
| `XCAFDoc_ShapeTool` | `InitDocument` 自动添加 | ✅ | ✅ |
| `TDataStd_Integer(42)` | `AddAttribute` | ✅ | ❌ |
| `TDataStd_Real(3.14)` | `AddAttribute` | ✅ | ❌ |
| `TDataStd_AsciiString` | `Set_s` (非XCAF框架) | ✅ | ❌ |

**所有非 XCAF 框架的属性类型全部丢失**——无论是 `AddAttribute` 还是 `Set_s` 方式添加，也无论是 TDataStd 标准类型还是 TNaming 类型。只有 `InitDocument` 自动添加的 XCAF 内置属性（`XCAFDoc_ShapeTool`）和 XCAF 框架方法添加的属性（`TDataStd_Name`）在重开后保留。

**完整测试脚本**: `_diag2_addattr.py`（已清理，代码见上）

---

### 8.4 诊断测试 3: NewDocument vs InitDocument

**测试目标**: 验证文档创建方式（`app.NewDocument()` vs 手动 `TDocStd_Document` + `app.InitDocument()`）是否影响属性持久化。

**Writer 代码**:

```python
# 方法 A: app.NewDocument()
app1 = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app1)
doc1 = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app1.NewDocument(TCollection_ExtendedString("BinXCAF"), doc1)

# 方法 B: 手动 + InitDocument()
app2 = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app2)
doc2 = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app2.InitDocument(doc2)
```

**Reader 结果**:

| 创建方式 | 保存前属性 | 重开后属性 | 结论 |
|---------|----------|----------|------|
| `NewDocument` | TDataStd_Integer | TDataStd_Name, XCAFDoc_ShapeTool | 属性丢失 |
| `InitDocument` | TDataStd_Name, XCAFDoc_ShapeTool, TDataStd_Integer | TDataStd_Name, XCAFDoc_ShapeTool | 属性丢失 |

**注**: `NewDocument` 创建的文档在保存前只有 `TDataStd_Integer`（无 XCAF 框架属性），但重开后 `XCAFDoc_ShapeTool` 被重新添加。这表明 XCAF 框架属性可能是由 `InitDocument`/`Open` 过程动态创建的，而非从 XBF 反序列化恢复。

**关键发现**: `NewDocument` vs `InitDocument` 对用户属性持久化无影响，两种创建方式的属性都在重开后丢失。

**完整测试脚本**: `_diag3_newdoc.py`（已清理，代码见上）

---

### 8.5 诊断测试 4: XBF 二进制内容分析

**测试目标**: 检查 XBF 文件是否包含用户属性的二进制数据，从而区分属性是在序列化（写）还是反序列化（读）阶段丢失。

**Writer 代码**:

```python
import struct

# 创建三种 XBF:
# 1. 空 XCAF (无用户属性)
doc_e = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app.InitDocument(doc_e)  # 只添加 XCAF 框架属性
app.SaveAs(doc_e, ...)   # → empty.xbf

# 2. + TDataStd_Integer(42)
doc_t = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app.InitDocument(doc_t)
doc_t.NewCommand()
lbl = doc_t.Main().NewChild()
i = TDataStd_Integer(); i.Set(42); lbl.AddAttribute(i)
doc_t.CommitCommand()
app.SaveAs(doc_t, ...)   # → test.xbf

# 3. + TNaming_Builder + TNaming_Selector
doc_n = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app.InitDocument(doc_n)
doc_n.NewCommand()
lbl_n = doc_n.Main().NewChild()
TNaming_Builder(lbl_n).Generated(box.wrapped)
sel_lbl = lbl_n.NewChild()
TNaming_Selector(sel_lbl).Select(top_face.wrapped, box.wrapped)
doc_n.CommitCommand()
app.SaveAs(doc_n, ...)   # → tnaming.xbf

# 比较文件大小
data_e = open("empty.xbf", "rb").read()
data_t = open("test.xbf", "rb").read()
data_n = open("tnaming.xbf", "rb").read()
```

**TDataStd_Integer GUID 字节序列**:
```python
# OCCT GUID: {2a96b61a-ec8e-11d0-bee9-0800c8662832}
guid_integer = bytes([
    0x1A, 0x6B, 0x96, 0x2A, 0x8E, 0xEC, 0xD0, 0x11,
    0xBE, 0xE9, 0x08, 0x00, 0xC8, 0x66, 0x28, 0x32,
])
```

**TNaming_NamedShape GUID 字节序列**:
```python
# OCCT GUID: {cabbc142-f216-11d2-9d90-00a0c9a0c4b9}
guid_named_shape = bytes([
    0x42, 0xC1, 0xBB, 0xCA, 0x16, 0xF2, 0xD2, 0x11,
    0x9D, 0x90, 0x00, 0xA0, 0xC9, 0xA0, 0xC4, 0xB9,
])
```

**结果**:

| 测试 | 文件大小 | vs 空文档 delta | 含 GUID? | 
|------|---------|---------------|----------|
| 空 XCAF | 1244 bytes | — | 不含 |
| + TDataStd_Integer(42) | 1313 bytes | **+69 bytes** | **二进制中未找到 GUID** |
| + TNaming + Selector | 9715 bytes | **+8471 bytes** | **二进制中未找到 GUID** |

**Delta 字节分析 (TDataStd_Integer 测试)**:
```
前 40 字节 hex:
00 04 00 00 00 14 00 00 00 1c 00 00 00 4e 00 6f 00
74 00 65 00 73 00 00 00 08 b6 96 2a 8b ec d0 11
be e7 08 00 09 dc 33 00 ...
```

其中包含文本 `N.o.t.e.s` 和部分看似 GUID 的字节片段（`08 b6 96 2a` 与 GUID 的第 12-15 字节 `BE E9 08 00` 不匹配），说明 delta 中确实有来自用户属性的序列化数据，但 GUID 编码格式可能与预期不同。

**Delta 字节分析 (TNaming 测试)**:
```
前 40 字节 hex:
00 00 00 f0 3f 00 00 00 00 00 00 f0 3f 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 80 07 00 00 00
00 00 00 00 00 00 00 00
```

包含大量 `3f f0` 模式（可能是浮点数 1.0 的 IEEE 754 编码），表明几何坐标数据被序列化。

**关键发现**:
- **数据确实被写入 XBF**：文件大小从 1244 → 1313 (+69) → 9715 (+8471) bytes，增量与用户属性数量正相关
- **GUID 未以预期格式出现**：TDataStd_Integer 和 TNaming_NamedShape 的 GUID 在整个 XBF 二进制中均未找到（搜索了标准 OCCT GUID 字节序）
- 这意味着属性数据可能以非标准编码写入，或 GUID 在序列化时被转换为其他标识符

**完整测试脚本**: `_diag4_binary.py`（已清理，代码见上）

---

### 8.6 诊断测试 5: TDF_Label 方法枚举与 FindAttribute 行为

**测试目标**: 枚举重开后 Label 上可用的方法，验证 FindAttribute 在各种属性类型上的行为（包括前文记录的崩溃）。

**方法枚举结果** (重开前后均可用的 `TDF_Label` 方法):

```python
# TDF_Label 完整方法列表
['AddAttribute', 'AttributesModified', 'Data', 'Depth', 'Dump', 'EntryDump',
 'ExtendedDump', 'Father', 'FindAttribute', 'FindChild', 'ForgetAllAttributes',
 'ForgetAttribute', 'HasAttribute', 'HasChild', 'HasGreaterNode', 'HasLowerNode',
 'Imported', 'IsAttribute', 'IsDescendant', 'IsDifferent', 'IsEqual', 'IsImported',
 'IsNull', 'IsRoot', 'MayBeModified', 'NbAttributes', 'NbChildren', 'NewChild',
 'Nullify', 'ResumeAttribute', 'Root', 'Tag', 'Transaction']
```

**FindAttribute 在保存前的行为** (TDataStd_Integer):

```python
guid_int = TDataStd_Integer.GetID_s()
ns_test = TDataStd_Integer()
found = lbl.FindAttribute(guid_int, ns_test)
# found = True ✅
# ns_test.Get() = 42 ✅
# ns_test.Label().IsNull() = True  ← Restore 壳对象!
# ns_test.ID() = Standard_GUID 对象 ✅
```

**Reader 进程 FindAttribute 行为** (独立 subprocess):

```python
# Reader 中调用:
i2 = TDataStd_Integer()
f = c.FindAttribute(TDataStd_Integer.GetID_s(), i2)
# → ACCESS VIOLATION, rc=3221225477 (0xC0000005)
```

**关键发现**:
- **保存前**: `FindAttribute` 对所有属性类型返回 True，但返回的对象是 Restore 壳（`Label().IsNull()==True`）。这不限于 TNaming——`TDataStd_Integer` 也有同样问题。
- **重开后**: `FindAttribute` 对**所有属性**（包括 TDataStd_Integer）触发 ACCESS VIOLATION 崩溃。这证实之前观察到的不是 "TNaming 特有的崩溃"，而是任何非 XCAF 框架属性的 FindAttribute 在重开后都崩溃。
- `HasAttribute()` 方法签名与 OCCT 文档不同——在 OCP 7.8.1.1 中它不接受 GUID 参数（`HasAttribute() -> bool`），这进一步证实了 OCP 绑定的不完整。

**完整测试脚本**: `_diag5_introspect.py`（已清理，代码见上）

---

### 8.7 诊断测试 6: NbAttributes 安全方法验证（绕过所有输出绑定）

**测试目标**: 使用不涉及任何输出参数的安全方法 `NbAttributes()` 和 `HasAttribute()` 做跨进程对比，彻底排除 OCP 输出绑定的干扰。

**Writer 代码**:

```python
app = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app)
doc = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app.InitDocument(doc)

doc.NewCommand()
lbl = doc.Main().NewChild()
i = TDataStd_Integer(); i.Set(42); lbl.AddAttribute(i)
doc.CommitCommand()

# 保存前验证
print(f"NbAttributes: {lbl.NbAttributes()}")  # → 3
print(f"HasAttribute: {lbl.HasAttribute()}")   # → True
```

**Reader 代码** (独立 `subprocess`):

```python
app = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app)
doc = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app.InitDocument(doc)
s = app.Open(TCollection_ExtendedString(xbf_path), doc)
c = doc.Main().FindChild(1, False)

# 使用零输出参数的安全方法
nb = c.NbAttributes()
has = c.HasAttribute()
```

**结果**:

| 指标 | Writer 进程 | Reader 进程 (PCDM_RS_OK) |
|------|-----------|------------------------|
| `NbAttributes()` | **3** | **2** |
| `HasAttribute()` | True | True |
| 差异属性 | TDataStd_Integer | — |

**关键发现**:

这是**结论性的证据**——`NbAttributes()` 和 `HasAttribute()` 都不使用任何输出参数（无 `Handle(TDF_Attribute)&` 语义），因此完全不受 OCP FindAttribute Restore 补丁的影响。在这个完全安全的测试路径上：

- Writer 进程: 3 个属性
- Reader 进程: 2 个属性

**TDataStd_Integer(42) 确实在跨进程 XBF 往返中丢失了**。这与 OCP 输出绑定缺陷无关，是真正的属性持久化失败。

**完整测试脚本**: `_diag6_hasattr.py`（已清理，代码见上）

---

### 8.8 诊断测试 7 (决定性): Retrieve() 返回值绕过 Open 输出参数

**测试目标**: "测试缺陷.md" 文档指出 `app.Open(path, doc)` 的 C++ 签名是 `Handle(TDocStd_Document)&`（输出引用），pybind11 可能无法将 C++ 新 Handle 回写到 Python 变量。本文档此前所有跨进程测试都使用了 `app.Open(path, pre_created_doc)` 模式，确实存在此风险。

`CDF_Application::Retrieve(folder, name)` 的返回值是 `Handle(CDM_Document)`（直接返回，不是输出参数），如果属性在 Retrieve() 返回的文档中存在，就证明问题仅在 Open 输出绑定。

**OCP 7.8.1.1 中 Retrieve() 的有效签名**:

```python
# 经过实验验证的签名:
doc = app.Retrieve(
    TCollection_ExtendedString(folder_path),
    TCollection_ExtendedString(file_name),
    True,   # UseStorageConfiguration
)
# 返回 TDocStd_Document 直接对象（非 Handle），无需 DownCast
```

**Reader 代码** (`_reader_retrieve.py`, 作为独立 subprocess 运行):

```python
import sys, json
from pathlib import Path
sys.path.insert(0, r"integrations\engineering_tools\src")
from OCP.XCAFApp import XCAFApp_Application
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDF import TDF_AttributeIterator

xbf_path = sys.argv[1]
app = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app)

p = Path(xbf_path).resolve()
folder = TCollection_ExtendedString(str(p.parent))
name = TCollection_ExtendedString(p.name)

# 关键: NO InitDocument(), NO pre-created doc, 使用返回值直接获取文档
doc = app.Retrieve(folder, name, True)
print("type=" + type(doc).__name__)           # TDocStd_Document ✅
print("children=" + str(doc.Main().HasChild()))  # True ✅

c = doc.Main().FindChild(1, False)
print("child_null=" + str(c.IsNull()))        # False ✅
print("nb=" + str(c.NbAttributes()))           # 2 ❌ (expected 3)

ait = TDF_AttributeIterator(c)
# → ["TDataStd_Name", "XCAFDoc_ShapeTool"]    # TDataStd_Integer(42) LOST

# FindAttribute 仍然崩溃:
from OCP.TDataStd import TDataStd_Integer
i2 = TDataStd_Integer()
c.FindAttribute(TDataStd_Integer.GetID_s(), i2)  # ACCESS VIOLATION
```

**结果**:

| 步骤 | 结果 |
|------|------|
| `Retrieve()` 返回类型 | `TDocStd_Document` ✅ |
| `Main().HasChild()` | `True` ✅ |
| `FindChild(1).IsNull()` | `False` ✅ |
| `NbAttributes()` | **2** ❌ (应为 3) |
| `TDF_AttributeIterator` | `["TDataStd_Name", "XCAFDoc_ShapeTool"]` ❌ |
| `FindAttribute(TDataStd_Integer)` | **ACCESS VIOLATION** ❌ (rc=3221225477) |

**结论**: 

`Retrieve()` 绕过了所有输出参数绑定的潜在问题——它返回的 `TDocStd_Document` 是一个真实的、被 XBF 数据填充的文档对象（标签树正确重建就是证明）。但 `TDataStd_Integer(42)` 仍然丢失，`FindAttribute` 仍然崩溃。

**"测试缺陷.md" 的 "Open 输出 Handle 未回写" 假设在此被证伪**。问题确实在属性持久化本身——要么属性未被正确序列化到 XBF，要么反序列化时属性驱动无法从二进制数据重建属性。

**但"测试缺陷.md"的其他判断仍然有重要价值**：
- Paste() 不使用输出参数（`const Handle<TDF_Attribute>&` 是输入引用）——正确
- 反序列化循环在 C++ 内部运行，pybind11 不参与每个属性的 Paste —— 正确
- 需要打开 OCCT 原生日志来定位确切故障点 —— 正确的下一步

### 8.9 测试缺陷文档中确认的先前测试错误

以下在"测试缺陷.md"中指出的先前测试缺陷已经过验证：

| 缺陷 | 状态 | 验证 |
|------|------|------|
| BinDrivers 测试 Reader 不匹配 Writer 格式 | **确认有效** | `reader_subprocess` 忽略了 `app_type` 参数 |
| NewDocument 反常结果暗示输出 Handle 未回写 | **确认但非根因** | Retrieve() 排除了此假设 |
| Paste 不使用输出参数 | **技术正确** | 上游源码证实 `const Handle&` 是输入 |
| 搜不到 GUID 是正常行为 | **技术正确** | 默认 GUID 的属性不写入 GUID 到 payload |
| NbAttributes 不能证明"属性真正丢失" | **被 Retrieve() 反驳** | NbAttributes 在 Retrieve 返回的真实文档上仍为 2 |

### 8.10 诊断测试总结矩阵

| # | 测试名称 | 隔离变量 | Writer 结果 | Reader 结果 | 结论 |
|---|---------|---------|-----------|-----------|------|
| 1 | BinDrivers vs BinXCAF | OCAF 格式 | — | — | **测试无效** — Reader 不匹配 Writer 格式 |
| 2 | AddAttribute vs Set_s | 属性创建方式 | 5属性 | 2属性 | 所有创建方式均丢失 |
| 3 | NewDocument vs InitDocument | 文档初始化 | 各不相同 | 均丢失 | NewDocument 反常, 但非根因 |
| 4 | XBF 二进制内容 | 序列化路径 | delta +69/+8471 bytes | — | 弱证据, 默认GUID不写入 |
| 5 | TDF_Label 方法 + FindAttribute | FindAttribute 行为 | Restore壳 | ACCESS VIOLATION | 不存在的属性 + 无 null guard |
| 6 | NbAttributes 安全方法 | 无输出参数 | Nb=3 | Nb=2 | 属性确实丢失, 但检查的可能是旧文档 |
| **7** | **Retrieve() 返回值** | **排除 Open 输出Handle** | Nb=3 | **Nb=2** ✅ | **决定性: 即使直接用返回值, 属性仍丢失** |

### 8.11 最终根因判断（第三轮修正）

综合 7 个诊断测试，可以排除以下假设：

| 假设 | 排除证据 |
|------|---------|
| "属性未写入 XBF" | 测试 4: 文件大小 +69/+8471 bytes delta（弱证据） |
| "同进程 Session 缓存导致" | 所有测试均使用独立 subprocess |
| "Open 输出 Handle 未回写 Python" | 测试 7: Retrieve() 直接返回文档，仍丢失 |
| "FindAttribute 输出绑定导致假阴性" | 测试 6: NbAttributes() 不使用输出参数 |
| "特定创建方式有问题" | 测试 2: AddAttribute 和 Set_s 均丢失 |
| "BinMNaming 驱动未注册" | OCCT 源码确认 C++ 注册链完整 |
| "pybind11 破坏单个 Attribute 的 Paste()" | OCCT 源码确认 Paste 全程在 C++ 内部, pybind11 不参与 |

**已修正的先前错误结论**:

1. ❌ "BinDrivers 连标签树都无法持久化" → **测试无效**（Reader 不匹配 Writer 格式）
2. ❌ "pybind11 破坏 BinMDataStd/BinMNaming 的 Paste 反序列化" → **机制上错误**（Paste 是 C++ 虚函数，pybind11 不介入）
3. ❌ "搜不到 GUID 说明使用了非标准编码" → **正常行为**（默认 GUID 的属性不写入 payload）
4. ❌ "NewDocument 与 InitDocument 对持久化无影响" → **测试揭示了输出Handle问题但非根因**

**当前最可能的根因**: 

在排除了 Open 输出绑定、单个属性 Paste binding、驱动注册缺失之后，剩余可能性集中在：

1. **序列化侧的属性类型 ID 映射问题**: BinXCAF 的文档检索驱动在序列化时需要为每个属性分配一个类型 ID，反序列化时通过类型 ID 查找对应的驱动。如果 OCP 的构建中类型 ID 映射表不完整（仅包含 XCAF 框架属性类型），用户属性在序列化时会被分配无效的类型 ID，或反序列化时无法找到对应驱动。

2. **OCP 构建配置缺失属性驱动注册**: 虽然原生 OCCT C++ 在 `BinDrivers::AttributeDrivers()` 中注册了所有驱动，但 OCP 的 pybind11 构建配置（`ocp.toml`）可能有条件编译选项排除了非 XCAF 属性驱动的 Python-facing 部分。即使 `.pyd` 文件存在，其内部的 C++ 注册可能未被触发。

3. **序列化时 CommitCommand 未完整提交属性变更**: OCP 的 `CommitCommand` 绑定可能有缺陷，导致用户添加的属性变更未被标记为需要序列化的"脏"数据。XCAF 框架属性由 `InitDocument` 自动创建并在 OCCT 内部管理修改状态，因此不受影响。

**区分这些假设需要**: OCCT 原生日志（`Message_PrinterOStream`）来确认 Reader 侧是否有 "type ID not registered" 或 "failure reading attribute" 告警。

---

## 附录 A. 测试环境详情

| 项目 | 值 |
|------|-----|
| Python | 3.11.9 (packaged by Anaconda) |
| CadQuery | 2.7.0 |
| OCP | 7.8.1.1 |
| OCCT (被绑定的原生库) | 7.8.1 |
| 操作系统 | Windows 11 Home China 10.0.22631 |
| 虚拟环境 | `auto_detection_process\.conda\` (embedded conda env) |
| 工作目录 | `e:\text_to_cad_improve\auto_detection_process\` |
| OCP 安装路径 | `.conda\Lib\site-packages\OCP\` |
| BinMNaming 模块位置 | `.conda\Lib\site-packages\OCP\BinMNaming\` (`.pyd` 文件) |
| BinMDataStd 模块位置 | `.conda\Lib\site-packages\OCP\BinMDataStd\` (`.pyd` 文件) |
| TDF_Label 方法数 | 33 个方法 (含 NbAttributes, HasAttribute, FindAttribute 等) |

## 附录 B. 关键 OCCT 源码引用

以下源码位置在实验分析中被引用（通过 `可能的问题.md` 文档提供的链接确认）：

| 文件 | 用途 |
|------|------|
| `OCCT V7_8_1/src/TDocStd/TDocStd_Application.cxx` | `SaveAs` 内部调用 `theDoc->Open(this)`, `Open` 中的 `CanRetrieve`/`IsInSession` 逻辑 |
| `OCCT V7_8_1/src/BinXCAFDrivers/BinXCAFDrivers.cxx` | `DefineFormat` → `BinDrivers::AttributeDrivers()` 的调用链 |
| `OCCT V7_8_1/src/BinDrivers/BinDrivers.cxx` | `AttributeDrivers()` 显式调用 `BinMDataStd::AddDrivers()`, `BinMNaming::AddDrivers()` 等 |
| `OCCT V7_8_1/src/TNaming/TNaming_Tool.cxx` | `CurrentShape` 对 `TNaming_SELECTED` 类型调 `Att->Label().FindAttribute(...)` |
| `OCCT V7_8_1/src/XCAFApp/XCAFApp_Application.cxx` | `InitDocument` 调用 `XCAFDoc_DocumentTool::Set(doc->Main())` |
| OCP issue #55 / PR #57 | `TDF_Label.FindAttribute` 输出绑定缺陷: 使用 `Restore()` 复制而非返回真实 Handle |

## 附录 C. 复现测试脚本清单

所有测试脚本在实验时位于 `_test_*.py` 和 `_diag*.py`（已清理）。本文档各节已包含足够完整的代码片段用于复现。建议按以下顺序复现：

1. **ABI Smoke Test** (§2.1) — 验证所有 API 的存在性
2. **TNaming_Selector 内存测试** (§2.2) — 验证 Select 在进程内工作
3. **TDF_Tool.Label_s 崩溃测试** (§2.3) — 验证 entry 恢复不可用
4. **跨进程 T0 测试** (§2.8) — 子进程验证跨进程持久化
5. **诊断测试 1** (§8.2) — BinDrivers vs BinXCAF
6. **诊断测试 2** (§8.3) — AddAttribute vs Set_s
7. **诊断测试 3** (§8.4) — NewDocument vs InitDocument
8. **诊断测试 4** (§8.5) — XBF 二进制分析
9. **诊断测试 5** (§8.6) — TDF_Label 方法枚举
10. **诊断测试 6** (§8.7) — NbAttributes 安全方法（决定性证据）
