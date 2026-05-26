# SeekFlow Engineering Tools — 架构分析与改进路线

## 当前状态（2026-05-26）

### ANSYS 18.1 — 🟢 稳定
- **方式**: APDL batch (`ansys181.exe -b -i input.inp -o output.out`)
- **稳定性**: 极高（30 年历史的命令行接口）
- **问题**: 无
- **6 个模板全部通过**

### SolidWorks 2025 — 🟡 能用但有技术债务
- **方式**: pywin32 (基础操作) + VBScript/cscript.exe (复杂特征)
- **问题**:
  1. `FeatureExtrusion2` 参数签名跨版本不稳定（23 参数 vs 文档 11-15）
  2. pywin32 延迟绑定无法匹配正确重载 → 必须绕道 VBScript
  3. VBScript 跨进程调用有 COM 连接断开风险（>200 次调用时）
  4. `On Error Resume Next` 掩盖了大量静默失败
- **为什么不用其他方式**:
  - makepy 无法自动生成（SolidWorks 类型库不支持 `GetTypeInfo()`）
  - C# COM Add-in 进程内调用是最彻底的解决方案，但需要额外编译部署
  - 直接写 STEP/DXF 文件不需要 SW COM，但失去了参数化能力

### NX 12.0 — 🟡 能用但脆弱
- **方式**: 文件队列桥接（Python 写 JSON → NX 内 Journal 消费）
- **问题**:
  1. NXOpen 必须在 NX 进程内运行，外部无法调用
  2. 轮询延迟（1 秒间隔）
  3. NX 12.0 内置 Python 3.6，语法受限
  4. NXOpen API 签名在不同 NX 版本间有差异
- **为什么不用其他方式**:
  - TCP/管道桥接更快但需要在 NX 内起 Socket Server
  - 直接生成 .prt 文件格式极其复杂（Siemens 专有二进制）

---

## 改进方案（按优先级）

### P0 — 立即执行

#### 1. 统一 SolidWorks 为纯 VBS 方案
不再混合 pywin32 + VBS。所有操作在一个 VBS 脚本中完成：
```
VBS: CreateObject → NewDocument → Sketch → Feature → SaveAs → 返回
Python: subprocess.run + 轮询文件是否生成
```
**优点**: 消除 sketch 编号不同步，单一进程执行，错误更容易追踪

#### 2. NX 桥接加入心跳检测
当前 bridge 无法检测是否存活。加入：
- 每 5 秒写 `running/heartbeat.json`
- 外部 Python 检查心跳，超时则重启 bridge
- job 超时自动移至 `failed/`

#### 3. 移除 `On Error Resume Next`
每个 VBS 操作后加显式错误检查：
```vbs
If Err.Number <> 0 Then
    WScript.Echo "ERR:" & Err.Number & " " & Err.Description
    WScript.Quit 1
End If
```
Python 端检查 `cscript` 返回码和 stderr 中的 ERR: 标记。

### P1 — 短期改进

#### 4. SolidWorks: 录制完整的宏模板
用户录制以下宏，替换现有 VBS 生成代码：
- 方块拉伸（验证 FeatureExtrusion2 签名）
- 拉伸切除（验证 FeatureCut4 签名）
- 法兰轮毂完整创建
- 齿轮齿廓（含渐开线曲线）

#### 5. NX: 录制 Journal 模板
用户录制以下 Journal，获取正确的 NX 12.0 API：
- 方块创建
- 圆柱体创建
- 布尔减法
- STEP 导出

### P2 — 中期改进

#### 6. SolidWorks: 生成 STEP 文件后导入
绕过 SW COM 完全创建几何：
1. Python 计算几何（纯数学）
2. 生成 STEP 文件（ISO 10303-21 文本格式）
3. 用 `sw.LoadFile4(step_path)` 导入
**优点**: 完全消除 COM 类型问题
**缺点**: 需要实现 STEP 文件生成器（约 500 行 Python）

#### 7. NX: TCP 管道替代文件队列
NX 内 Journal 起 `socket` server，Python 通过 TCP 发 job。
**优点**: 毫秒级延迟，双向通信，可靠投递
**缺点**: NX Journal 需改造

---

## 当前已稳定可用的 API 清单

### SolidWorks (VBScript 可靠)
| API | 参数 | 用途 |
|---|---|---|
| `NewDocument(tpl, 0, 0, 0)` | str, int×3 | 新建零件 |
| `SelectByID2(name, type, x,y,z, append, mark, nullvar, opt)` | str×2, float×3, bool, int, var, int | 选择实体 |
| `InsertSketch2(True)` | bool | 进入/退出草图 |
| `CreateCenterRectangle(x0,y0,z0, x1,y1,z1)` | float×6 | 画中心矩形 |
| `CreateCircle(x0,y0,z0, xr,yr,zr)` | float×6 | 画圆 |
| `CreateLine(x1,y1,z1, x2,y2,z2)` | float×6 | 画线段 |
| `FeatureExtrusion2(Sd,Flip,Dir, T1,T2, D1,D2, Dch1,Dch2, ...)` | 23 params | 拉伸特征 |
| `FeatureCut4(...)` | ~18 params | 拉伸切除 |
| `SaveAs3(path, 0, 2)` | str, int, int | 保存文件 |
| `Extension.SaveAs(path, 0, 0, Nothing, 0, 0)` | str, int×5, var | 导出 STEP |

### NX (NXOpen Python Journal 可靠)
| API | 用途 |
|---|---|
| `Parts.NewDisplay("Millimeters", Units.Millimeters)` | 新建显示零件 |
| `Features.CreateBlockFeatureBuilder(Feature.Null)` | 块构建器 |
| `Features.CreateCylinderBuilder(Feature.Null)` | 圆柱构建器 |
| `Features.CreateSubtractFeature(target, bool, [tool], bool, bool)` | 布尔减法 |
| `DexManager(session).CreateStep214Creator()` | STEP 导出 |
| `Point3d(x, y, z)` | 点构造 |
| `Vector3d(x, y, z)` | 向量构造 |
| `SaveAs(path)` | 保存 |

### ANSYS (subprocess 可靠)
| 模板 | 分析类型 |
|---|---|
| `static_cantilever_beam_rect_apdl` | 静力 |
| `plate_with_hole_tension_apdl` | 应力集中 |
| `beam_thermal_apdl` | 稳态热 |
| `cantilever_modal_apdl` | 模态 |
| `buckling_column_apdl` | 屈曲 |
| `bilinear_plastic_apdl` | 塑性 |
