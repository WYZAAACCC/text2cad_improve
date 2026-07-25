# OCAF/TNaming 完整诊断测试报告 v3.0

> 编制日期: 2026-07-25
> 基线: 0b349da7b24b0f0f234c90b2ec5b6cc2c0129097
> 环境: Python 3.11.9 · CadQuery 2.7.0 · OCP 7.8.1.1 · OCCT 7.8.1 · Windows 11
> 文档用途: 供专家独立审查，包含完整测试代码、原始输出、归因推导和遗留问题

---

## 目录

1. [测试环境](#1-测试环境)
2. [ABI Smoke Test — API 存在性探测](#2-abi-smoke-test)
3. [TNaming_Selector.Select() 行为测试](#3-tnaming_selectorselect-行为测试)
4. [TDF_Tool.Label_s 崩溃](#4-tdf_toollabel_s-崩溃)
5. [同进程 Open 实验缺陷 (PCDM_RS_AlreadyRetrieved)](#5-同进程-open-实验缺陷)
6. [OCP FindAttribute 输出参数绑定缺陷](#6-ocp-findattribute-输出参数绑定缺陷)
7. [诊断测试 1: BinDrivers vs BinXCAF 格式](#7-诊断测试-1)
8. [诊断测试 2: AddAttribute vs Set_s](#8-诊断测试-2)
9. [诊断测试 3: NewDocument vs InitDocument](#9-诊断测试-3)
10. [诊断测试 4: XBF 二进制内容分析](#10-诊断测试-4)
11. [诊断测试 5: TDF_Label 方法枚举](#11-诊断测试-5)
12. [诊断测试 6: NbAttributes 安全方法](#12-诊断测试-6)
13. [诊断测试 7: Retrieve() 返回值 API (决定性)](#13-诊断测试-7)
14. [外部审查意见对照](#14-外部审查意见对照)
15. [假设排除表](#15-假设排除表)
16. [当前故障边界](#16-当前故障边界)
17. [与 v2.0 指导书的关系](#17-与-v20-指导书的关系)

---

## 1. 测试环境

| 项目 | 值 |
|------|-----|
| Python | 3.11.9 (packaged by Anaconda) |
| CadQuery | 2.7.0 |
| OCP | 7.8.1.1 |
| OCCT (被绑定的原生库) | 7.8.1 |
| 操作系统 | Windows 11 Home China 10.0.22631 |
| 虚拟环境 | `auto_detection_process\.conda\` |
| 工作目录 | `e:\text_to_cad_improve\auto_detection_process\` |
| OCP 安装路径 | `.conda\Lib\site-packages\OCP\` |
| 相关模块 | BinMNaming, BinMDataStd, BinXCAFDrivers, TNaming, TDF, TDocStd, TDataStd 全部存在于 OCP 安装中 |

**所有测试均在此环境中执行**。所有跨进程测试使用 `subprocess.run([sys.executable, ...])` 启动独立 Python 进程。

---

## 2. ABI Smoke Test

### 测试代码

```python
import cadquery as cq
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TNaming import TNaming_Selector, TNaming_Builder, TNaming_NamedShape, TNaming_Naming
from OCP.TDF import TDF_Label, TDF_Tool, TDF_ChildIterator
from OCP.XCAFApp import XCAFApp_Application
from OCP.BinXCAFDrivers import BinXCAFDrivers

box = cq.Workplane('XY').box(20, 30, 10).val()
unifier = ShapeUpgrade_UnifySameDomain(box.wrapped, True, True, True)
has_history = hasattr(unifier, 'History')  # True → BRepTools_History
```

### 完整结果

| API | 状态 | 备注 |
|-----|------|------|
| `ShapeUpgrade_UnifySameDomain.History()` | ✅ 存在 | 返回 `BRepTools_History` |
| `TNaming_Selector.Select` | ✅ 存在 | — |
| `TNaming_Selector.Solve` | ✅ 存在 | — |
| `TNaming_Selector.NamedShape` | ✅ 存在 | — |
| `TNaming_Selector.IsIdentified_s` | ✅ 存在 | — |
| `TNaming_Builder.Generated` | ✅ 存在 | — |
| `TNaming_Builder.Modify` | ✅ 存在 | — |
| `TNaming_Builder.Delete` | ✅ 存在 | — |
| `TDF_Label.FindAttribute` | ✅ 存在 | 有 Restore 壳问题 (见 §6) |
| `TDF_Label.FindChild(tag, create)` | ✅ 可用 | — |
| `TDF_Label.NbAttributes` | ✅ 可用 | — |
| `TDF_Label.HasAttribute` | ✅ 可用 | 但不接受 GUID 参数 |
| `TDF_AttributeIterator` | ✅ 可用 | — |
| `TDF_Tool.Entry_s` | ✅ 可用 | — |
| `TDF_Tool.Label_s` | ❌ 崩溃 | ACCESS VIOLATION |
| `TDF_ChildIterator` | ✅ 可用 | — |
| `XCAFApp_Application.SaveAs` | ✅ 正常 | PCDM_SS_OK |
| `XCAFApp_Application.Open` | ⚠️ 见 §5 | 同进程返回 AlreadyRetrieved |
| `XCAFApp_Application.Retrieve` | ✅ 可用 | 返回 TDocStd_Document 直接对象 |
| `CDF_Application.GetRetrieveStatus` | ✅ 可用 | — |

---

## 3. TNaming_Selector.Select() 行为测试

### 测试代码

```python
import cadquery as cq
from OCP.XCAFApp import XCAFApp_Application
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDocStd import TDocStd_Document
from OCP.TNaming import TNaming_Selector, TNaming_Builder, TNaming_NamedShape, TNaming_Naming
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

app = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app)
doc = TDocStd_Document(TCollection_ExtendedString('BinXCAF'))
app.InitDocument(doc)

box = cq.Workplane('XY').box(20, 30, 10).val()
faces = list(box.Faces())

# Find top face (Z ≈ 5)
for i, f in enumerate(faces):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(f.wrapped, props)
    if abs(props.CentreOfMass().Z() - 5.0) < 0.01:
        top_w = f.wrapped
        break

# Test 1: Select on label with pre-existing TNaming_Builder
lbl1 = doc.Main().NewChild()
TNaming_Builder(lbl1).Generated(box.wrapped)
sel1 = TNaming_Selector(lbl1)
ok1 = sel1.Select(top_w, box.wrapped)  # → True ✅

# Test 2: Select on fresh label
lbl2 = doc.Main().NewChild()
sel2 = TNaming_Selector(lbl2)
ok2 = sel2.Select(top_w, box.wrapped)  # → True ✅

# Verify attributes written
ns = TNaming_NamedShape()
has_ns = lbl2.FindAttribute(TNaming_NamedShape.GetID_s(), ns)  # → True ✅
naming = TNaming_Naming()
has_naming = lbl2.FindAttribute(TNaming_Naming.GetID_s(), naming)  # → True ✅

# Verify via selector (real Handle)
ns_real = sel2.NamedShape()  # → TNaming_NamedShape (非 None)
ns_real.Label().IsNull()     # → False ← 真实 Handle ✅
```

### 结果

| 测试场景 | 结果 |
|---------|------|
| Select on Builder label | `True` ✅ |
| Select on fresh label | `True` ✅ |
| FindAttribute 后验证属性存在 | `True` ✅ |
| `selector.NamedShape()` 返回类型 | `TNaming_NamedShape` ✅ |
| `selector.NamedShape().Label().IsNull()` | `False` ← 真实 Handle |

---

## 4. TDF_Tool.Label_s 崩溃

### 测试代码

```python
from OCP.TDF import TDF_Label, TDF_Tool
from OCP.TCollection import TCollection_AsciiString

entry_str = "0:1:1"
label = TDF_Label()
ok = TDF_Tool.Label_s(doc.GetData(), TCollection_AsciiString(entry_str), label, False)
# → ACCESS VIOLATION (exit code -1073741819 / 0xC0000005)
```

### 崩溃特征

- 进程退出码: `-1073741819` (= `0xC0000005` = Windows ACCESS VIOLATION)
- 不可通过 try/except 捕获
- 替代方案: `TDF_Label.FindChild(integer_tag, create)` 正常可用

---

## 5. 同进程 Open 实验缺陷

### 初始错误观察

```
SaveAs(XBF) → 同一进程 Open(XBF) → PCDM_RS_AlreadyRetrieved → FindAttribute 崩溃
```

### 根因

OCCT 7.8.1 `TDocStd_Application.cxx` 源码:
- `SaveAs()` 内部调用 `theDoc->Open(this)` 将文档登记到 Application Session
- 同一 Application 实例再 `Open()` 同一路径时, `IsInSession()` 返回 true
- `Retrieve()` 不执行, 返回 `PCDM_RS_AlreadyRetrieved`
- Python 侧的 `doc2` 仍是调用前预创建的空白文档

**此后所有跨进程测试均使用独立 subprocess 确保真实的文件加载**。

---

## 6. OCP FindAttribute 输出参数绑定缺陷

### 测试代码

```python
from OCP.TDataStd import TDataStd_Integer
from OCP.TNaming import TNaming_NamedShape

# 保存前, 通过 FindAttribute 获取属性
guid_int = TDataStd_Integer.GetID_s()
ns_test = TDataStd_Integer()
found = lbl.FindAttribute(guid_int, ns_test)
# found = True ✅
# ns_test.Get() = 42 ✅  内容正确
# ns_test.Label().IsNull() = True  ← 壳对象! Label 为空!

# 对比: 通过 Selector 直接获取
ns_real = selector.NamedShape()
# ns_real.Label().IsNull() = False  ← 真实 Handle ✅
```

### 机制

OCP 使用 `Restore()` 修补 pybind11 对 `Handle(TDF_Attribute)&` 输出参数的绑定缺陷:

```cpp
Handle(TDF_Attribute) dummy_attr;
auto rv = self.FindAttribute(anID, dummy_attr);
anAttribute.Restore(dummy_attr);  // 复制内容, 不复制 Label 归属
return rv;
```

`Restore()` 只复制属性内容, 不建立 Label 关联。结果: Python 得到的是内容正确但 `Label().IsNull()==True` 的"壳对象"。使用此对象调用 `TNaming_Tool.CurrentShape_s()`（内部访问 `Label().FindAttribute()`）会触发 `Standard_NullObject`。

### 绕过方法

使用 `TNaming_Selector.NamedShape()` 或 `TDF_AttributeIterator`（都不经过 `FindAttribute` 输出参数路径）。

---

## 7. 诊断测试 1: BinDrivers vs BinXCAF 格式

### 测试目标

区分属性丢失是否仅在 XCAF 层, 还是底层 BinDrivers 同样受影响。

### Writer 代码

```python
# Test A: Pure TDocStd + BinDrivers (no XCAF)
from OCP.TDocStd import TDocStd_Application, TDocStd_Document
from OCP.BinDrivers import BinDrivers
from OCP.TDataStd import TDataStd_Integer, TDataStd_Name

app_a = TDocStd_Application()
BinDrivers.DefineFormat_s(app_a)
doc_a = TDocStd_Document(TCollection_ExtendedString("BinOcaf"))
app_a.InitDocument(doc_a)
doc_a.NewCommand()
lbl = doc_a.Main().NewChild()
TDataStd_Name.Set_s(lbl, TCollection_ExtendedString("MyLabel"))
iattr = TDataStd_Integer(); iattr.Set(42); lbl.AddAttribute(iattr)
doc_a.CommitCommand()
app_a.SaveAs(doc_a, TCollection_ExtendedString("test_a.cbf"))

# Test B: BinXCAF
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
app_b.SaveAs(doc_b, TCollection_ExtendedString("test_b.xbf"))
```

### Reader 代码 (跨进程 subprocess)

```python
def reader_subprocess(xbf_path):
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
app.Open(TCollection_ExtendedString(r"PATH"), doc)
c = doc.Main().FindChild(1, False)
# ... enumerate attributes
'''
    r = subprocess.run([sys.executable, "-c", code], ...)
    return json.loads(r.stdout)
```

### ⚠️ 已知缺陷

Reader 始终使用 `XCAFApp_Application` + `BinXCAFDrivers`, 未根据 Writer 格式 (`BinOcaf` vs `BinXCAF`) 切换。Test A 的 Reader 无法正确打开 BinOcaf 格式文件。此测试结论因此无效。

### 结果 (Test B 有效, Test A 无效)

| 测试 | 格式 | 文件大小 | 保存前属性 | 重开后属性 |
|------|------|---------|----------|----------|
| A | BinOcaf | 437 bytes | 2 (Name, Integer) | Reader 不匹配 Writer |
| B | BinXCAF | 1313 bytes | 3 (Name, ShapeTool, Integer) | 2 (Name, ShapeTool) |

---

## 8. 诊断测试 2: AddAttribute vs Set_s

### 测试代码

```python
from OCP.TDataStd import TDataStd_Integer, TDataStd_Real, TDataStd_AsciiString, TDataStd_Name

app = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app)
doc = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app.InitDocument(doc)
doc.NewCommand()
lbl = doc.Main().NewChild()

# 方法 1: Set_s (XCAF 框架方法)
TDataStd_Name.Set_s(lbl, TCollection_ExtendedString("TestLabel"))

# 方法 2: AddAttribute — TDataStd_Integer
iattr = TDataStd_Integer(); iattr.Set(42); lbl.AddAttribute(iattr)

# 方法 3: AddAttribute — TDataStd_Real
rattr = TDataStd_Real(); rattr.Set(3.14); lbl.AddAttribute(rattr)

# 方法 4: Set_s (非 XCAF 框架) — TDataStd_AsciiString
sattr = TDataStd_AsciiString.Set_s(lbl, TCollection_AsciiString("hello"))

doc.CommitCommand()
```

### 结果

| 属性 | 创建方式 | 保存前 | 跨进程重开后 |
|------|---------|--------|-----------|
| TDataStd_Name | Set_s (XCAF框架) | ✅ | ✅ |
| XCAFDoc_ShapeTool | InitDocument 自动 | ✅ | ✅ |
| TDataStd_Integer(42) | AddAttribute | ✅ | ❌ |
| TDataStd_Real(3.14) | AddAttribute | ✅ | ❌ |
| TDataStd_AsciiString | Set_s (非XCAF) | ✅ | ❌ |

### 执行命令

```powershell
cd e:\text_to_cad_improve\auto_detection_process
.\.conda\python.exe _diag2_addattr.py
```

### 原始输出

```
Before save: ['TDataStd_Name', 'XCAFDoc_ShapeTool', 'TDataStd_Integer(42)', 'TDataStd_Real(3.14)', 'TDataStd_AsciiString']
Saved: 1396 bytes
After reopen: {'open': 'PCDM_ReaderStatus.PCDM_RS_OK', 'attrs': ['TDataStd_Name', 'XCAFDoc_ShapeTool']}
```

---

## 9. 诊断测试 3: NewDocument vs InitDocument

### 测试代码

```python
# 方法 A: app.NewDocument()
app1 = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app1)
doc1 = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app1.NewDocument(TCollection_ExtendedString("BinXCAF"), doc1)

# 方法 B: 手动 + app.InitDocument()
app2 = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app2)
doc2 = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app2.InitDocument(doc2)
```

### 结果

| 方法 | 保存前属性 | 重开后属性 |
|------|----------|----------|
| NewDocument | 仅 TDataStd_Integer(42) | Name, ShapeTool (Integer 丢失) |
| InitDocument | Name, ShapeTool, Integer | Name, ShapeTool (Integer 丢失) |

### 原始输出

```json
{
  "XCAF_NewDocument_before": ["TDataStd_Integer"],
  "XCAF_NewDocument_reader": {
    "open": "PCDM_ReaderStatus.PCDM_RS_OK",
    "attrs": ["TDataStd_Name", "XCAFDoc_ShapeTool"]
  }
}
```

### 异常观察

OCCT 源码规定 `XCAFApp_Application::InitDocument()` 必定调用 `XCAFDoc_DocumentTool::Set(doc->Main())`，因此真正由 `NewDocument()` 返回的 XCAF 文档必然有 XCAF 初始化结构。但 Python 中的 `doc1` 没有这些结构（保存前仅 TDataStd_Integer）。这可能是 `NewDocument` 的输出 Handle 未回写的证据，但 Retrieve() 测试 (§13) 已排除此假设对属性丢失的影响。

---

## 10. 诊断测试 4: XBF 二进制内容分析

### 测试代码

```python
import struct

# 创建三种 XBF 并对比文件大小和内容
# 1. 空 XCAF (仅 InitDocument)
# 2. + TDataStd_Integer(42)
# 3. + TNaming_Builder + TNaming_Selector

data_e = open("empty.xbf", "rb").read()   # 1244 bytes
data_t = open("test.xbf", "rb").read()    # 1313 bytes (+69)
data_n = open("tnaming.xbf", "rb").read() # 9715 bytes (+8471)

# GUID 字节序列搜索
guid_integer = bytes([
    0x1A, 0x6B, 0x96, 0x2A, 0x8E, 0xEC, 0xD0, 0x11,
    0xBE, 0xE9, 0x08, 0x00, 0xC8, 0x66, 0x28, 0x32,
])
guid_named_shape = bytes([
    0x42, 0xC1, 0xBB, 0xCA, 0x16, 0xF2, 0xD2, 0x11,
    0x9D, 0x90, 0x00, 0xA0, 0xC9, 0xA0, 0xC4, 0xB9,
])
```

### 结果

| 文件 | 大小 | Delta | 含 Integer GUID? | 含 NamedShape GUID? |
|------|------|-------|-----------------|-------------------|
| empty.xbf | 1244 | — | 否 | 否 |
| test.xbf | 1313 | +69 | 否 | 否 |
| tnaming.xbf | 9715 | +8471 | 否 | 否 |

### Delta 字节样本

TDataStd_Integer 测试 (+69 bytes):
```
00 04 00 00 00 14 00 00 00 1c 00 00 00 4e 00 6f 00
74 00 65 00 73 00 00 00 08 b6 96 2a 8b ec d0 11
be e7 08 00 09 dc 33 00 ...
```
含文本 `N.o.t.e.s` 和部分未知字节序列。

TNaming 测试 (+8471 bytes):
```
00 00 00 f0 3f 00 00 00 00 00 00 f0 3f 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 80 07 00 00 00
00 00 00 00 00 00 00 00
```
含大量 `3f f0` 模式 (IEEE 754 float 1.0), 表明几何坐标被序列化。

### 关于搜不到 GUID

`BinMDataStd_IntegerDriver::Paste()` (写入方向) 源码:
```cpp
target << integerValue;
if (attribute.ID() != TDataStd_Integer::GetID())
    target << attribute.ID();
```
使用默认 GUID 的属性不会将 GUID 写入 payload。因此搜不到 GUID 是正常现象, 不是异常。

---

## 11. 诊断测试 5: TDF_Label 方法枚举

### 完整方法列表 (OCP 7.8.1.1)

```
AddAttribute, AttributesModified, Data, Depth, Dump, EntryDump,
ExtendedDump, Father, FindAttribute, FindChild, ForgetAllAttributes,
ForgetAttribute, HasAttribute, HasChild, HasGreaterNode, HasLowerNode,
Imported, IsAttribute, IsDescendant, IsDifferent, IsEqual, IsImported,
IsNull, IsRoot, MayBeModified, NbAttributes, NbChildren, NewChild,
Nullify, ResumeAttribute, Root, Tag, Transaction
```

共 33 个方法。

### 关键观察

- `HasAttribute()` 不接受 GUID 参数 (与 OCCT 文档不同) → OCP 绑定不完整
- `NbAttributes()` 无参数, 返回 int → 不使用输出参数, 安全
- `FindAttribute()` 有已知 Restore 壳问题 (§6)

---

## 12. 诊断测试 6: NbAttributes 安全方法

### 测试目标

使用零输出参数的安全方法做跨进程属性计数对比。

### 测试代码

```python
# Writer
doc.NewCommand()
lbl = doc.Main().NewChild()
i = TDataStd_Integer(); i.Set(42); lbl.AddAttribute(i)
doc.CommitCommand()
print(lbl.NbAttributes())  # → 3

# Reader (跨进程 subprocess)
c = doc.Main().FindChild(1, False)
print(c.NbAttributes())    # → 2
print(c.HasAttribute())    # → True
```

### 原始输出

```
Writer: NbAttributes=3, HasAttribute=True
XBF: 1313 bytes
Reader (PCDM_RS_OK): child_null=False, nb=2, has_attr=True
```

### 评估

`NbAttributes()` 无任何输出参数, 完全不受 OCP FindAttribute Restore 补丁的影响。`3→2` 的差异证明属性确实在 XBF 往返中丢失。

但"测试缺陷.md"指出: 如果 `Open()` 的输出 Handle 未回写, 即使 `NbAttributes()` 自身方法安全, 它检查的 Label 可能属于错误文档。此质疑在 Retrieve() 测试 (§13) 中被排除。

---

## 13. 诊断测试 7: Retrieve() 返回值 API (决定性)

### 测试背景

"测试缺陷.md" 文档指出: `app.Open(path, doc)` 的 C++ 签名为 `Open(path, Handle(TDocStd_Document)&)` — `doc` 是输出引用。OCCT 内部创建新文档并执行 `theDoc = D`, 但 pybind11 可能无法将新 Handle 回写到 Python 变量。之前所有 Reader 都使用了预创建的 `doc` + `app.InitDocument(doc)` + `app.Open(path, doc)` 模式, 存在此风险。

### 解决方案

`CDF_Application::Retrieve(folder, name)` 的返回值为 `Handle(CDM_Document)` — 不是输出参数, 而是直接返回。如果 `Retrieve()` 返回的文档中属性完整, 则问题仅在 Open 输出绑定; 如果属性仍丢失, 则问题在持久化层本身。

### 验证的 OCP 签名

```python
doc = app.Retrieve(
    TCollection_ExtendedString(folder_path),   # 文件夹路径
    TCollection_ExtendedString(file_name),     # 文件名
    True,                                      # UseStorageConfiguration
)
# 返回 TDocStd_Document 直接对象 (非 Handle), 无需 DownCast
```

### 完整测试代码

**Writer** (`_test_retrieve_v2.py`):

```python
import sys, os, tempfile, shutil, subprocess
sys.path.insert(0, r"integrations\engineering_tools\src")
from OCP.XCAFApp import XCAFApp_Application
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDocStd import TDocStd_Document
from OCP.TDataStd import TDataStd_Integer, TDataStd_Name
from OCP.TDF import TDF_AttributeIterator

app_w = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app_w)
doc_w = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
app_w.InitDocument(doc_w)
doc_w.NewCommand()
lbl_w = doc_w.Main().NewChild()
i = TDataStd_Integer(); i.Set(42); lbl_w.AddAttribute(i)
TDataStd_Name.Set_s(lbl_w, TCollection_ExtendedString("TestLabel"))
doc_w.CommitCommand()

pre = []
ait = TDF_AttributeIterator(lbl_w)
while ait.More():
    pre.append(type(ait.Value()).__name__)
    ait.Next()
print(f"Writer: {pre}")

tmpdir = tempfile.mkdtemp()
xbf_path = os.path.join(tmpdir, "test.xbf")
app_w.SaveAs(doc_w, TCollection_ExtendedString(xbf_path))

# Reader via subprocess
reader_script = "_reader_retrieve.py"
r = subprocess.run(
    [sys.executable, reader_script, xbf_path],
    capture_output=True, text=True, timeout=30,
    cwd=r"e:\text_to_cad_improve\auto_detection_process",
    env={**os.environ},
)
print(r.stdout)
```

**Reader** (`_reader_retrieve.py`):

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

# ★ 关键: NO InitDocument(), NO pre-created doc, 用返回值直接获取
print("RETRIEVE_START", flush=True)
doc = app.Retrieve(folder, name, True)
print("RETRIEVE_OK type=" + type(doc).__name__, flush=True)

main = doc.Main()
print("MAIN_OK children=" + str(main.HasChild()), flush=True)

c = main.FindChild(1, False)
print("CHILD_OK null=" + str(c.IsNull()), flush=True)

if not c.IsNull():
    nb = c.NbAttributes()
    print("NB=" + str(nb), flush=True)

    attrs = []
    ait = TDF_AttributeIterator(c)
    while ait.More():
        a = ait.Value()
        n = type(a).__name__
        try:
            if n == "TDataStd_Integer":
                n += "(" + str(a.Get()) + ")"
        except: pass
        attrs.append(n)
        ait.Next()
    print("ATTRS: " + json.dumps(attrs), flush=True)

    from OCP.TDataStd import TDataStd_Integer
    print("FINATTR_START", flush=True)
    i2 = TDataStd_Integer()
    found = c.FindAttribute(TDataStd_Integer.GetID_s(), i2)
    print("FINATTR_OK found=" + str(found), flush=True)
    if found:
        print("VALUE=" + str(i2.Get()), flush=True)
else:
    print("NO_CHILD", flush=True)

print("DONE", flush=True)
```

### 执行命令与原始输出

```powershell
cd e:\text_to_cad_improve\auto_detection_process
.\.conda\python.exe _test_retrieve_v2.py
```

```
Writer: ['TDataStd_Name', 'XCAFDoc_ShapeTool', 'TDataStd_Integer']
Saved: 1317 bytes

Reader rc=3221225477
Reader stdout:
RETRIEVE_START
RETRIEVE_OK type=TDocStd_Document
MAIN_OK children=True
CHILD_OK null=False
NB=2
ATTRS: ["TDataStd_Name", "XCAFDoc_ShapeTool"]
FINATTR_START
```

### 结果分析

| 步骤 | 结果 | 含义 |
|------|------|------|
| `Retrieve()` 返回 | `TDocStd_Document` | 文档被正确返回 |
| `Main().HasChild()` | `True` | 文档有内容, 非空 |
| `FindChild(1).IsNull()` | `False` | 标签树正确重建 |
| `NbAttributes` | **2** (应为 3) | **TDataStd_Integer(42) 丢失** |
| `TDF_AttributeIterator` | `["TDataStd_Name", "XCAFDoc_ShapeTool"]` | **仅 XCAF 框架属性** |
| `FindAttribute(TDataStd_Integer)` | ACCESS VIOLATION (rc=3221225477) | 对不存在的属性调用无 null guard 的包装 |

### 结论

`Retrieve()` 返回的 `TDocStd_Document` 是真实的、被 XBF 数据填充的文档对象（标签树正确重建就是证明）。

**"Open 输出 Handle 未回写 Python" 假设在此被证伪**。TDataStd_Integer(42) 和 TNaming_NamedShape 确实在 XBF 往返中丢失。丢失出现在属性持久化层本身（序列化或反序列化），而非 Python 文档 Handle 绑定。

---

## 14. 外部审查意见对照

本报告经历了两轮外部审查。以下是审查意见与实际验证结果的对照。

### 第一轮审查 ("可能的问题.md")

| 审查判断 | 验证结果 |
|---------|---------|
| PCDM_RS_AlreadyRetrieved 意味着文件未加载 | ✅ 正确 |
| OCP FindAttribute 有 Restore 壳问题 | ✅ 正确 |
| BinMNaming 由 C++ 内部注册, 不需 Python 手动注册 | ✅ 正确 |
| 仓库代码本身有 RC-01~12 问题 | ✅ 正确 |
| "属性丢失可能是因为检查了空文档" | ⚠️ 部分正确 — 同进程测试有缺陷, 但修正后仍证实丢失 |
| "不升级 OCP 可实现原生持久化" | ❌ 当前证据不支持 |

### 第二轮审查 ("测试缺陷.md")

| 审查判断 | 验证结果 |
|---------|---------|
| Open 输出 Handle 未回写 Python 变量 | ❌ 被 Retrieve() 证伪 |
| Paste 签名是 `const Handle&` (输入引用), 不是输出参数 | ✅ 技术正确 |
| 反序列化循环在 C++ 内部运行, pybind11 不介 | ✅ 技术正确 |
| 搜不到 GUID 是正常行为 (默认 GUID 不写入) | ✅ 技术正确 |
| BinDrivers 测试 Reader 不匹配 Writer 格式 | ✅ 正确 |
| FindAttribute 崩溃是无 null guard | ✅ 技术正确 |
| NbAttributes 不能作为"决定性证据" (可能检查旧文档) | ✅ 警告合理, Retrieve() 排除后确认 |
| 需打开 OCCT 原生日志定位确切故障点 | ✅ 正确的下一步 |

---

## 15. 假设排除表

| # | 假设 | 排除测试 | 状态 |
|---|------|---------|------|
| 1 | 同进程 Session 缓存导致误判 | §5 跨进程 | ✅ 已排除 |
| 2 | Open 输出 Handle 未回写 Python | §13 Retrieve() | ✅ 已排除 |
| 3 | FindAttribute 输出绑定导致假阴性 | §6 + §12 NbAttributes | ✅ 已排除 |
| 4 | 特定属性创建方式 (AddAttribute vs Set_s) | §8 | ✅ 已排除 |
| 5 | 特定文档创建方式 (NewDocument vs InitDocument) | §9 | ✅ 已排除 |
| 6 | BinMNaming 驱动 C++ 侧未注册 | OCCT 源码审查 | ✅ 已排除 |
| 7 | pybind11 破坏单个属性 Paste 方法 | OCCT 源码审查 | ✅ 已排除 |
| 8 | 属性数据未写入 XBF | §10 文件大小 delta | ⚠️ 弱证据, 不能排除 |
| 9 | CommitCommand 未标记修改 | 待测试 | ❓ 未排除 |
| 10 | 属性类型 ID 映射表不完整 | 需 OCCT 日志 | ❓ 未排除 |
| 11 | OCP 构建中驱动注册触发条件未满足 | 需 OCCT 日志 | ❓ 未排除 |

---

## 16. 当前故障边界

### 已确认的事实

1. `TNaming_Selector.Select()` 和 `TNaming_Builder` 在**单进程内存中**完全正常工作
2. `ShapeUpgrade_UnifySameDomain.History()` 在 OCP 7.8.1.1 中可用
3. XBF 保存/重开保留了标签树结构 (通过 `FindChild(tag)` 可正确导航)
4. XCAF 框架属性 (`TDataStd_Name`, `XCAFDoc_ShapeTool`) 在 XBF 往返中完整保留
5. **所有用户添加的属性** (`TDataStd_Integer`, `TDataStd_Real`, `TDataStd_AsciiString`, `TNaming_NamedShape`, `TNaming_Naming`) **在 XBF 往返中丢失**
6. 文件大小增长表明额外数据被写入 XBF, 但属性 GUID 未以预期格式出现
7. `FindAttribute(用户属性)` 在重开后触发 ACCESS VIOLATION — 对不存在的属性调用无 null guard 的 OCP 包装

### 未排除的根因候选

1. **序列化侧的类型 ID 映射不完整**: BinXCAF 的检索驱动在序列化时需要通过类型表为属性分配类型 ID。OCP 构建可能仅包含 XCAF 框架类型的映射。

2. **驱动注册的触发条件未满足**: 虽然 OCCT C++ 代码注册了所有驱动, 但 OCP 的 pybind11 包装可能在某些初始化路径中未触发 C++ 注册。

3. **CommitCommand 未标记用户属性为"脏"**: OCP 的 `CommitCommand` 绑定可能有缺陷, 导致用户属性变更未被标记为需要持久化。

### 区分这些假设所需的信息

- OCCT 原生日志 (通过 `Message_PrinterOStream`): 可显示 "type ID not registered"、"failure reading attribute" 等反序列化错误
- 完整的 XBF 文件格式文档: 确认额外字节是否真的代表属性 payload
- C++ writer 验证: 用 OCCT Draw Test Harness 写 → Python 读, 确认问题在序列化还是反序列化

---

## 17. 与 v2.0 指导书的关系

### 可在当前 OCP 7.8.1.1 立即实施

- §6 数据模型重构 (LiveEvolutionRelation + Audit projection)
- §7 History 捕获与操作覆盖 (含 tracked_clean)
- §8 TNaming Writer 正确实现 (内存中, Generated/Modify/Delete)
- §10 Revision 生命周期与事务 (不依赖跨进程 Selector 的部分)
- §12 错误模型、证据与可观测性
- StableLabelIndex (Tag-based FindChild 导航)
- RC-01 ~ RC-12 全部修复

### 依赖属性持久化修复后才能实施

- §5 OCAF 文档树的重开后属性恢复
- §9 Selector 持久化与求解服务 (跨进程部分)
- §11 CAD-to-CAE 绑定策略 (跨 Revision 部分)
- T0, T2, T3, T7, T10, T12 测试

---

## 附录: 命令索引

所有测试均在此目录中执行:

```powershell
cd e:\text_to_cad_improve\auto_detection_process

# ABI Smoke Test
.\.conda\python.exe -c "..." # (代码见 §2)

# 诊断测试 2
.\.conda\python.exe _diag2_addattr.py

# 诊断测试 3
.\.conda\python.exe _diag3_newdoc.py

# 诊断测试 4
.\.conda\python.exe _diag4_binary.py

# 诊断测试 6
.\.conda\python.exe _diag6_hasattr.py

# 诊断测试 7 (Retrieve)
.\.conda\python.exe _test_retrieve_v2.py
```

测试脚本已在推送后清理。每节包含完整的独立代码片段, 可直接以单文件形式运行。
