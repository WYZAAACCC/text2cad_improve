# OCP 7.8.1.1 API 限制与已知问题

> 日期: 2026-07-26
> 环境: Python 3.11.9, CadQuery 2.7.0, OCP 7.8.1.1 (OCCT 7.8.1)
> 用途: 专家审查参考——记录所有在实施过程中遇到的 OCP API 限制

---

## 一、致命崩溃（ACCESS VIOLATION）

### 1. `TNaming_Selector.Solve()` 在被选面完全删除后崩溃

```
Windows fatal exception: access violation (0xC0000005)
位置: selection_service.py solve() → selector.Solve(valid_labels)
触发条件: 被选面已通过 Boolean cut 完全删除，DELETED relations 已写入 OCAF
```

**严重度**: 高。Python 无法捕获（C++ 级崩溃）。
**当前策略**: 跳过 Solve 调用，通过 history 中的 DELETED relations 前置判断。
**建议**: 子进程隔离 Solve worker，或等待 OCP 补丁。

### 2. `TNaming` 对象析构时崩溃

```
returncode: 3221226505 (0xC0000009)
触发条件: 子进程退出时，OCP TNaming_Builder/TNaming_Selector 对象析构
```

**严重度**: 中。仅影响子进程退出，数据已正确持久化。
**当前策略**: 子进程 `print(flush=True)` + 忽略非零 returncode。
**建议**: 子进程使用 `os._exit(0)` 或在写入完成后显式 `del` 所有 OCP 对象。

### 3. `app.Retrieve()` 在垃圾数据上崩溃

```
Windows fatal exception: access violation
位置: compat.py retrieve_xcaf_document() → app.Retrieve()
触发条件: 文件不是合法 XBF 格式（随机字节、截断文件）
```

**严重度**: 中。生产环境中可能遇到损坏文件。
**当前策略**: 在 Retrieve 之前添加 `min_size` 检查（8 字节）。不保证防御所有损坏格式。
**建议**: 子进程隔离 Retrieve，或在打开前验证 XBF magic bytes。

### 4. `TNaming_Selector.Select()` 在空文档上崩溃

```
Windows fatal exception: access violation
位置: selection_service.py create() → selector.Select()
触发条件: OCAF 文档中没有任何 TNaming_Builder 属性时调用 Select
```

**严重度**: 中。
**当前策略**: 在调用 `Select()` 之前必须先写入至少一个 `TNaming_Builder.Generated()`。
已在代码和测试中添加注释和前置条件检查。
**建议**: 在 `create()` 中添加显式守卫，检测文档中是否存在 TNaming 属性。

---

## 二、API 不存在或签名不兼容

### 5. `TDataStd_AsciiString.Get_s()` 不存在

```
AttributeError: type object 'OCP.OCP.TDataStd.TDataStd_AsciiString' has no attribute 'Get_s'
Did you mean: 'Set_s'?
```

**影响**: 无法通过静态方法读取已写入的 AsciiString 属性值。
**当前策略**: `_read_policy()` 和 `_read_contract()` 退化为返回 None（best-effort）。
**后果**: Policy 和 SemanticContract 无法在 Solve 时可靠恢复，依赖调用者传入。
**建议**: 使用 `TDF_AttributeIterator` + `attr.Get()` 实例方法，或封装为 `compat` 函数。

### 6. `TDataStd_Integer.Get_s()` 不存在

```
AttributeError: type object 'OCP.OCP.TDataStd.TDataStd_Integer' has no attribute 'Get_s'
Did you mean: 'Set_s'?
```

**影响**: 无法读取持久化的 Integer 属性值（revision counters 等）。
**当前策略**: `StableLabelIndex.load_from_ocaf()` 中 `try/except` 跳过计数器恢复。
**后果**: 索引计数器在重开后从默认值开始，可能导致 Tag 分配冲突。
**建议**: 同上，使用 Iterator + 实例方法。

### 7. `IsKind(GetID_s())` 类型不兼容

```
TypeError: IsKind(): incompatible function arguments
Invoked with: <TNaming_NamedShape>, <Standard_GUID>
Supported: IsKind(Standard_Type) or IsKind(str)
```

**影响**: 无法使用 GUID 进行类型检查。
**当前策略**: 改用 `attr.DynamicType().Name() == "TNaming_NamedShape"` 字符串比较。
**后果**: 字符串比较比类型检查慢，且可能因 OCCT 版本变更而失效。

### 8. `TNaming_Selector.IsIdentified_s()` 签名不同

```
IsIdentified_s(): incompatible function arguments
Invoked with: ()
Supported: (access: TDF_Label, selection: TopoDS_Shape, NS: TNaming_NamedShape, Geometry: bool = False) -> bool
```

**影响**: 不是简单的 `selector.IsIdentified()` 调用，而是静态函数需要 3+ 参数。
**当前策略**: 不使用 `IsIdentified`，改用 `NamedShape()` 非空检查。

### 9. `TNaming_Tool.CurrentShape_s()` 接受 NamedShape 而非 Label

```
CurrentShape_s(): incompatible function arguments
Invoked with: <TDF_Label>
Supported: (NS: TNaming_NamedShape) -> TopoDS_Shape
```

**当前策略**: 正确的调用链: `selector.NamedShape()` → `TNaming_Tool.CurrentShape_s(ns)`。

### 10. `TNaming_Tool.NamedShape_s()` 接受 (Shape, Label) 而非 (Label)

```
NamedShape_s(): incompatible function arguments
Invoked with: <TDF_Label>
Supported: (aShape: TopoDS_Shape, anAcces: TDF_Label) -> TNaming_NamedShape
```

**当前策略**: 直接从 `TNaming_Selector.NamedShape()` 获取，不使用 `TNaming_Tool.NamedShape_s()`。

### 11. `TDataStd_AsciiString.Set_s()` 接受 `TCollection_AsciiString` 而非 `TCollection_ExtendedString`

```
TypeError: Set_s(): incompatible function arguments
Invoked with: <TDF_Label>, <TCollection_ExtendedString>
Supported: (label, string: TCollection_AsciiString)
```

**当前策略**: 写入时使用 `TCollection_AsciiString(data)` 而非 `TCollection_ExtendedString`。

### 12. `TopoDS_Shape.HashCode()` 可能导致崩溃

在 `explode_entities()` 中尝试使用 `HashCode(99999)` 去重时失败。
**当前策略**: `explode_entities()` 不去重，直接返回所有枚举实体。

---

## 三、空标签不持久化

**发现**: OCAF 的 `SaveAs()` 不会序列化没有任何属性（TDataStd_Name 等）的空标签。
**影响**: 如果只调用 `FindChild(TAG, True)` 创建标签但不附加属性，该标签在 `SaveAs` → `Retrieve` 后消失。
**当前策略**: 所有结构标签都附加 `TDataStd_Name`，DesignRoot 标签附加名称。已在 `OcafRepository.create()` 和 `OcafDocumentSession.create()` 中实现。

---

## 四、Windows 特定问题

### 文件锁定

`os.replace()` 在 Windows 上对 OCAF Application Session 持有的文件失败（`PermissionError: WinError 32`）。
**当前策略**: `publish()` 使用 `shutil.copy2()` + `os.remove()`（best-effort）替代 `os.replace()`。

### 中文路径编码

`TCollection_ExtendedString(str(path))` 默认 `isMultiByte=False`，将 UTF-8 字节错误解释为 Latin-1。
**修复**: `ext_utf8(value)` → `TCollection_ExtendedString(str(value), True)`。

### 同进程 AlreadyRetrieved

`SaveAs()` 将文档注册到 Application Session → 同进程 `Open()` 返回 `PCDM_RS_AlreadyRetrieved`。
**修复**: 使用 `app.Retrieve(folder, name, True)` 替代 `app.Open(path, doc)`。

---

## 五、设计约束（非 OCP 缺陷，但需注意）

### Writer 不管理事务

`TopologyNamingWriter` 设计为纯写入，事务由 Revision Session 统一管理。这是正确的架构设计，但调用者必须自行 `begin_write()`/`commit_write()`。

### TNaming_Builder 重复写入

在同一个 Label 上多次调用 `TNaming_Builder(label).Generated(shape)` 会覆盖之前的命名。每个独立关系需要独立的子标签。

---

## 六、汇总：对当前系统的实际影响

| 限制 | 影响的功能 | 严重度 |
|------|-----------|--------|
| Solve on deleted face crash | T4 Delete Solve | 高 |
| TNaming destructor crash | 子进程测试 | 中 |
| Retrieve on garbage crash | 损坏文件恢复 | 中 |
| Select on empty doc crash | 首次创建 Selection | 中 |
| Get_s() not available | Policy/Contract 恢复 | 中 |
| Get_s() not available | StableLabelIndex 计数器恢复 | 中 |
| IsKind(GetID_s()) mismatch | 属性类型检查 | 低 |
| IsIdentified_s() signature | 选择验证 | 低 |
| HashCode crash | 实体去重 | 低 |
| 空标签不持久化 | 标签树结构 | 低（已修复） |
| Windows 文件锁定 | 原子发布 | 低（已修复） |
| 中文路径编码 | 路径处理 | 低（已修复） |
