# SeekFlow 工程软件集成架构文档

## 概述

SeekFlow 通过三种不同的技术路径分别调用 SolidWorks 2025、Siemens NX 12.0 和 ANSYS 18.1。三款软件的调用方式各不相同，原因在于它们各自提供的自动化接口完全不同。

---

## 1. SolidWorks 2025 — COM 自动化 + VBScript 桥接

### 1.1 当前方案

```
Python (pywin32)          VBScript (cscript.exe)
    │                          │
    ├─ NewDocument             │
    ├─ SelectByID2             │
    ├─ InsertSketch2           │
    ├─ CreateCenterRectangle   │
    ├─ SaveAs3                 │
    ├─ Extension.SaveAs        │
    │                          ├─ FeatureExtrusion2 (23参数!)
    │                          ├─ FeatureCut4
    │                          └─ FeatureCircularPattern2
    │                          │
    └─ 保存 / 导出 ←──────────┘
```

**核心原理**：SolidWorks 暴露了完整的 COM 接口（`SldWorks.Application`），Python 通过 `pywin32` 调用。但复杂方法（如拉伸、扫描）的参数签名在不同版本间变化巨大，pywin32 的延迟绑定无法正确解析。

### 1.2 为什么分两路

| 操作 | 路径 | 原因 |
|---|---|---|
| NewDocument, SelectByID2, InsertSketch2, SaveAs3 | pywin32 直调 | 参数简单（字符串、布尔），延迟绑定无问题 |
| FeatureExtrusion2 | VBScript | **实际签名有 23 个参数**，官方文档只列了 11-15 个。pywin32 的 `IDispatch::Invoke` 无法匹配正确的重载，始终报 `TYPE_MISMATCH` |
| FeatureCut4, FeatureFillet2 | VBScript | 同上 |
| SaveAs3（STL 格式） | VBScript | STL 翻译器需要进程内类型库（VBA 环境），外部 COM 调用 SaveAs3 对非原生格式返回非零错误码 |

**VBScript 为什么能成功**：VBScript 通过 `cscript.exe` 运行，Windows 脚本宿主使用原生的 COM 类型解析，无需经过 pywin32 的 Python→COM 类型映射层。

### 1.3 关键发现：FeatureExtrusion2 的 23 参数签名

从 SolidWorks 2025 宏录音得到的真实签名：

```vb
Part.FeatureManager.FeatureExtrusion2 _
    True,       ' Sd (单方向)
    False,      ' Flip (反向)
    False,      ' Dir (方向)
    0, 0,       ' T1, T2 (终止条件: 0=Blind)
    0.03, 0.03, ' D1, D2 (深度, 米为单位)
    False, False,           ' Dch1, Dch2 (拔模方向)
    False, False,           ' (未文档化)
    1.74533E-02, 1.74533E-02, ' 拔模角度 (1° 弧度)
    False, False,           ' (未文档化)
    False, False,           ' (未文档化)
    True, True, True,       ' (未文档化)
    0, 0,                   ' (未文档化)
    False                   ' (未文档化)
```

文档声称只有 10-15 个参数，实际有 23 个。这是 pywin32 无法调用的根本原因——动态派发在参数数量不匹配时会报 `TYPE_E_TYPEMISMATCH`，且没有任何机制能自动探测正确的重载。

### 1.4 替代方案对比

| 方案 | 可行性 | 优点 | 缺点 |
|---|---|---|---|
| **pywin32 直调** (当前) | 部分可用 | 简单，无需额外依赖 | 复杂方法 TYPE_MISMATCH |
| **VBScript 桥接** (当前) | ✅ 全功能 | 原生 COM，签名正确 | 跨进程，无法获取返回值 |
| **makepy 静态绑定** | ❌ 不可用 | 生成完整 Python 包装 | SW 类型库不支持 `GetTypeInfo()`，makepy 无法自动生成 |
| **SolidWorks API SDK (C#)** | 可行但重 | 最完整的 COM 支持 | 需要 C# 项目，部署复杂 |
| **宏文件 (.swp)** | 可行 | 可在 SW 内部运行 | 需要预录制，不够动态 |
| **PySW (第三方)** | ❌ 已停更 | 曾简化调用 | 不支持 SW2022+ |
| **REST API** | ❌ 不存在 | — | SW 无 HTTP API |

---

## 2. Siemens NX 12.0 — NXOpen Journal + 文件队列桥接

### 2.1 当前方案

```
SeekFlow Agent                NX 进程内
    │                              │
    ├─ 写入 job JSON ──────────→ pending/*.json
    │                              │
    │                         nx_bridge_bootstrap.py
    │                         (NXOpen Python Journal)
    │                              │
    │                         ├─ NewDisplay
    │                         ├─ CreateBlockFeatureBuilder
    │                         ├─ CreateCylinderBuilder
    │                         ├─ CreateSubtractFeature (布尔减法)
    │                         ├─ SaveAs
    │                         └─ 写入 result JSON
    │                              │
    ├─ 轮询 ←───────────────── done/*.result.json
```

**核心原理**：NXOpen Python 只能在 NX 进程内运行。外部 Python 无法 `import NXOpen`——NX 使用自己内置的 Python 3.6 解释器。

### 2.2 为什么用文件队列

| 约束 | 解决方案 |
|---|---|
| NXOpen 只能在 NX 进程内运行 | `nx_bridge_bootstrap.py` 作为长驻 Journal 在 NX 内部运行 |
| NX 内置 Python 3.6（非系统 Python） | 脚本使用 `# type:` 注释格式，禁用 `from __future__ import annotations` |
| 无法从外部进程调用 NXOpen | 文件队列：外部写 JSON → NX 内部读取 → 执行 → 写结果 JSON |
| `run_journal.exe` 可冷启动 | `D:\nx\NXBIN\run_journal.exe script.py` 在无 GUI 情况下执行 Journal |

### 2.3 关键 API 发现

所有发现均来自 NX 12.0 自带的 SDK 示例代码 (`D:\nx\UGOPEN\SampleNXOpenApplications\Python\`) 以及运行时反射：

| 发现 | 错误做法 | 正确做法 |
|---|---|---|
| BlockFeatureBuilder 空参数 | `None` | `NXOpen.Features.Feature.Null` |
| SetOriginAndLengths 参数类型 | `float` | **`str`**（如 `"100"` 而非 `100.0`） |
| Point3d 构造 | `CreatePoint(Point3d(…))` | `NXOpen.Point3d(0,0,0)` 直接传入 |
| CylinderBuilder 直径/高度 | `cfb.Diameter = 16` | `cfb.Diameter.RightHandSide = "16"` |
| 布尔减法 CreateSubtractFeature | 2 参数 | **5 参数**：`(target_body, bool, [tool_bodies], bool, bool)` |
| STEP 导出 | `CreateStep214Exporter()` (不存在) | `DexManager(session).CreateStep214Creator()` |
| 中文基准面名 | `"Front Plane"` | `"前视基准面"` |

### 2.4 替代方案对比

| 方案 | 可行性 | 说明 |
|---|---|---|
| **NXOpen Journal + 文件队列** (当前) | ✅ | 最稳定，适合自动化 |
| NXOpen .NET/C++ API | 可行 | 功能最全，但开发成本高 |
| NXOpen Python 直接调用 | ❌ | 必须在 NX 进程内，外部 Python 无法 import |
| `subprocess` 直接跑 Journal | ✅ | `run_journal.exe` 单次执行，适合简单任务 |
| TCP/管道桥接 | 可行 | 比文件队列更快，需要在 NX 内起 Socket Server |
| Teamcenter/PLM 集成 | 大型方案 | 企业级方案，远超当前需求 |
| NX 批处理模式 | 部分可用 | `ugraf.exe -batch` 可跑部分 API，GUI 操作不可用 |

---

## 3. ANSYS 18.1 — APDL 批处理 + subprocess

### 3.1 当前方案

```
Python
    │
    ├─ 生成 APDL 输入文件 (.inp)
    │    ├─ static_cantilever_beam_rect_apdl()
    │    ├─ plate_with_hole_tension_apdl()
    │    ├─ beam_thermal_apdl()
    │    ├─ cantilever_modal_apdl()
    │    ├─ buckling_column_apdl()
    │    └─ bilinear_plastic_apdl()
    │
    ├─ subprocess: ansys181.exe -b -i input.inp -o output.out
    │
    └─ 解析 result_summary.txt
```

**核心原理**：ANSYS Mechanical APDL 支持纯命令行批处理模式 (`-b` 参数)。输入是 APDL 文本文件，输出是 `.out` 日志 + 二进制结果文件 + 自定义文本输出。

### 3.2 为什么用 subprocess

| 对比项 | APDL batch | PyMAPDL (新版) | PyAnsys |
|---|---|---|---|
| **版本要求** | ANSYS 任意版本 | ANSYS 2021 R1+ | ANSYS 2022 R2+ |
| **通信方式** | 标准输入/输出文件 | CORBA/gRPC | gRPC |
| **稳定性** | ✅ 30 年历史，极稳 | 中等 | 新，API 仍变化 |
| **ANSYS 18.1 兼容** | ✅ | ❌ (需要 gRPC) | ❌ |
| **进程控制** | `subprocess.run()` | Python 进程内 | Python 进程内 |
| **调试** | 查看 .out 文件 | Python traceback | Python traceback |

**ANSYS 18.1 只有 APDL batch 一条路**。新版 PyMAPDL/PyAnsys 需要的 gRPC 接口在 ANSYS 2021 R1 才引入。18.1 的 CORBA 接口已废弃且在新版 Python 中不可用。

### 3.3 6 个已验证的 APDL 模板

| 模板 | 分析类型 | 物理 | 单元类型 | 求解器 |
|---|---|---|---|---|
| `static_cantilever_beam_rect_apdl` | 静力 | 线弹性 | SOLID185 | 静态 |
| `plate_with_hole_tension_apdl` | 静力 | 平面应力 | PLANE182 | 静态 |
| `beam_thermal_apdl` | 稳态热 | 热传导 | SOLID70 | 稳态热 |
| `cantilever_modal_apdl` | 模态 | 特征值 | SOLID185 | Block Lanczos |
| `buckling_column_apdl` | 屈曲 | 稳定性 | BEAM188 | 特征值屈曲 |
| `bilinear_plastic_apdl` | 静力 | 塑性 BKIN | SOLID185 | 非线性静态 |

### 3.4 替代方案对比

| 方案 | 可行性 | 说明 |
|---|---|---|
| **APDL batch + subprocess** (当前) | ✅ | ANSYS 18.1 唯一稳定方案 |
| PyMAPDL (mapdl) | ❌ | 需要 ANSYS 2021 R1+ |
| PyAnsys (pyansys) | ❌ | 需要 ANSYS 2022 R2+ |
| Workbench Journal | 可行 | 录制 XML Journal，通过 `runwb2` 回放。但 XML 格式复杂，难以动态生成 |
| ACT (Application Customization Toolkit) | 可行 | .NET API，开发环境配置复杂 |
| ANSYS AEDT (电子) | 无关 | 电磁仿真，非结构分析 |
| LS-DYNA 输入文件 | 可行 | 类似 APDL 方式，但完全不同的事件处理 |

---

## 4. 三款软件对比总结

| 维度 | SolidWorks 2025 | NX 12.0 | ANSYS 18.1 |
|---|---|---|---|
| **自动化接口** | COM (`SldWorks.Application`) | NXOpen Python Journal | APDL 命令行 |
| **进程模型** | 外部进程（COM 跨进程） | 内部进程（文件队列桥接） | 外部进程（subprocess） |
| **通信方向** | 单向调用 | 请求-响应（文件队列） | 生成文件→执行→解析 |
| **核心瓶颈** | 参数签名版本差异 | 必须在 NX 内运行 | 老版本无 gRPC |
| **参数系统** | 23 参数（文档不完整） | `Null`/`str`/`RightHandSide` | 全文本 APDL |
| **单位系统** | 米（API 内部） | 毫米（用户定义） | 用户定义 |
| **错误处理** | `On Error Resume Next` | traceback + file | .out 中的 `*** ERROR ***` |
| **启动速度** | ~3 秒 (COM) | ~4 秒 (Journal) | ~10 秒 (ANSYS 启动) |

---

## 5. 技术债务与下一步

### 已解决
- [x] SolidWorks FeatureExtrusion2 23 参数签名
- [x] NX `Feature.Null` vs `None`
- [x] NX `SetOriginAndLengths` str 参数
- [x] NX `CreateSubtractFeature` 5 参数签名
- [x] NX `DexManager` STEP 导出
- [x] ANSYS 6 种分析类型的 APDL 模板

### 需要录制宏才能继续
- [ ] SolidWorks: `InsertHelix` + `InsertProtrusionSwept3`（螺旋线+扫描）→ 齿轮弹簧
- [ ] SolidWorks: `FeatureShell` 参数签名（抽壳厚度+面选择）
- [ ] NX: SketchBuilder + RevolveBuilder（旋转体：阶梯轴、法兰）
- [ ] NX: EdgeBlendBuilder.AddChainset 参数签名（圆角需要 ScCollector）

### 可能的路线
1. **短期**：用户录制上述 4 个宏 → 我更新代码 → 扩展测试矩阵
2. **中期**：NX 文件队列升级为 TCP 管道（减少轮询延迟）
3. **长期**：SolidWorks 切换到 C# COM Add-in 进程内调用（完全消除类型问题）
