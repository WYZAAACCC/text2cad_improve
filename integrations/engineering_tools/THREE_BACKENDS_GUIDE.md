# 三后端工业软件调用指南

本文档描述如何在 `integrations/engineering_tools` 中调用 SolidWorks 2025、Siemens NX 12.0、ANSYS 18.1。

---

## 目录
1. [SolidWorks 2025 COM 自动化](#1-solidworks-2025-com-自动化)
2. [Siemens NX 12.0 Job Queue Bridge](#2-siemens-nx-120-job-queue-bridge)
3. [ANSYS 18.1 APDL 批处理](#3-ansys-181-apdl-批处理)
4. [统一构建入口 (Build Planner)](#4-统一构建入口-build-planner)

---

## 1. SolidWorks 2025 COM 自动化

### 1.1 前置条件

```text
- Windows 系统
- SolidWorks 2025 安装并注册 COM
- pywin32: pip install pywin32
- 零件模板: C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot

环境变量 (可选):
  SOLIDWORKS_PART_TEMPLATE = 零件模板路径
  SOLIDWORKS_VISIBLE       = 1 (显示SW窗口) / 0 (隐藏)
  SOLIDWORKS_ENABLED       = 1 (启用) / 0 (禁用)
```

### 1.2 连接与健康检查

```python
from pathlib import Path
from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient

# 连接 (visible=True 会显示 SolidWorks 窗口)
client = SolidWorksClient(
    visible=True,
    part_template=Path(r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot"),
).connect()

# 健康检查
info = client.health_check()
# 返回: {"connected": True, "revision_number": "33.5.0", "visible": True}
print(f"SW Revision: {info['revision_number']}")
```

### 1.3 可用操作

#### 1.3.1 工程级操作 (通过 Tool 注册)

这些通过 `build_solidworks_tools()` 注册为 SeekFlow Tool：

| Tool 名称 | 功能 | 参数 |
|-----------|------|------|
| `solidworks_health_check` | 健康检查 | 无 |
| `solidworks_create_box_part` | 创建矩形块 | `length_mm, width_mm, height_mm, out_sldprt, [out_step]` |
| `solidworks_create_flanged_hub_part` | 创建法兰毂 | `flange_dia_mm, flange_thickness_mm, hub_dia_mm, hub_height_mm, bore_dia_mm, bolt_pcd_mm, bolt_dia_mm, bolt_count, out_sldprt, [out_step]` |
| `solidworks_export_step` | SLDPRT→STEP | `input_sldprt, out_step` |
| `solidworks_import_step_as_part` | STEP→SLDPRT | `input_step, out_sldprt` |

```python
# 获取所有注册的 SW tools
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.solidworks.tools import build_solidworks_tools

config = EngineeringToolsConfig(workspace_root=Path("./workspace"))
tools = build_solidworks_tools(config)
for t in tools:
    print(f"  {t.name}: {t.description[:60]}...")
```

#### 1.3.2 COM 客户端底层方法

直接操作 SolidWorks COM 对象：

```python
client = SolidWorksClient(visible=True, part_template=Path(template_path)).connect()

# ── 创建新零件 ──
model = client.new_part()

# ── 矩形块 (单位: 米) ──
client.create_extruded_box(model, length_m=0.100, width_m=0.060, height_m=0.030)

# ── 法兰毂 (单位: 米) ──
client.create_flanged_hub(
    model,
    flange_dia_m=0.080, flange_h_m=0.010,
    hub_dia_m=0.040, hub_h_m=0.030,
    bore_dia_m=0.020, bolt_pcd_m=0.060,
    bolt_dia_m=0.008, bolt_count=4,
)

# ── 保存 ──
client.save_as(model, Path("output.SLDPRT"))
client.export_step(model, Path("output.step"))

# ── STEP 导入 (用于工业级齿轮) ──
ok = client.import_step_as_part(
    step_path=Path("canonical_gear.step"),
    out_sldprt=Path("imported.SLDPRT"),
)
# 返回 True 仅当 SLDPRT 存在且 size > 0

# ── 打开已有文档 ──
doc = client.open_document(Path("existing.SLDPRT"))

# ── 关闭 ──
client.close_all()  # 关闭所有文档
client.close()      # 释放引用
```

#### 1.3.3 LEGACY 方法 (不注册为 Tool，仅内部使用)

以下方法**已从 Tool 注册表中移除**，仅保留为 COM 内部方法：

```python
# ⚠️ LEGACY - 非工程级，不被统一构建调用
client.create_spur_gear(model, module_m=0.003, teeth=20, ...)
client.create_spur_gear_involute(model, module_m=0.003, teeth=20, ...)
client.create_spur_gear_true_involute(model, module_m=0.003, teeth=20, ...)
```

### 1.4 单位转换

```text
SW COM API 使用 METRES
CAD-IR / Tool 层使用 MILLIMETRES
转换: mm_value / 1000.0 = m_value
```

### 1.5 齿轮的工业级路径

```
齿轮 primitive → CQ_Gears (deterministic) → CadQuery BREP → canonical STEP
  → SolidWorks LoadFile2(step) → import
  → SaveAs3(sldprt) → native SLDPRT
```

---

## 2. Siemens NX 12.0 Job Queue Bridge

### 2.1 前置条件

```text
- Siemens NX 12.0 安装
- run_journal.exe: D:\nx\NXBIN\run_journal.exe
- bridge bootstrap: integrations/engineering_tools/src/seekflow_engineering_tools/nx/nx_bridge_bootstrap.py
- job queue 目录: %HOME%\seekflow_workspace\nx_jobs\

环境变量:
  NX_JOB_ROOT = C:\Users\<user>\seekflow_workspace\nx_jobs
```

### 2.2 启动 NX Bridge

```bash
# 杀死旧进程
taskkill //F //IM run_journal.exe 2>&1

# 启动 (必须设置 NX_JOB_ROOT)
set NX_JOB_ROOT=C:\Users\mycomputer\seekflow_workspace\nx_jobs

# 方式1: 通过 CMD 启动
"D:\nx\NXBIN\run_journal.exe" "E:\auto_detection_process\integrations\engineering_tools\src\seekflow_engineering_tools\nx\nx_bridge_bootstrap.py"

# 方式2: 通过 Python 启动 (推荐, 确保环境变量正确传递)
python -c "
import subprocess, os
os.environ['NX_JOB_ROOT'] = r'C:\Users\mycomputer\seekflow_workspace\nx_jobs'
exe = r'D:\nx\NXBIN\run_journal.exe'
bridge = r'E:\auto_detection_process\integrations\engineering_tools\src\seekflow_engineering_tools\nx\nx_bridge_bootstrap.py'
subprocess.Popen([exe, bridge], env=os.environ)
"
```

### 2.3 检查 Bridge 状态

```python
from seekflow_engineering_tools.nx.job_queue import NXJobQueue
from pathlib import Path
import time, json

# 使用与 bridge bootstrap 相同的 JOB_ROOT
nx_root = Path.home() / "seekflow_workspace" / "nx_jobs"
q = NXJobQueue(nx_root)

# 检查 bridge 是否存活 (heartbeat 每5秒更新)
status = q.bridge_status(stale_after_s=30)
print(f"Bridge running: {status['bridge_running']}")
print(f"Heartbeat age: {status.get('heartbeat_age_s', 0):.1f}s")
print(f"Queue: {q.queue_status()}")
```

**关键提示**: `NX_JOB_ROOT` 必须匹配 `nx_bridge_bootstrap.py` 的默认值:
```python
JOB_ROOT = Path(os.environ.get("NX_JOB_ROOT", str(Path.home() / "seekflow_workspace" / "nx_jobs")))
```

### 2.4 提交 Job

```python
from seekflow_engineering_tools.nx.job_queue import NXJobQueue
from pathlib import Path

q = NXJobQueue(Path.home() / "seekflow_workspace" / "nx_jobs")

# 可用的 action
# - create_block_part
# - create_block_with_hole
# - create_l_bracket
# - create_stepped_block
# - export_step
# - import_step_as_prt

# 提交创建块的 job
job_id = q.submit("create_block_part", {
    "length_mm": 100,
    "width_mm": 60,
    "height_mm": 20,
    "out_prt": r"E:\output\block.prt",
})

# 等待完成
try:
    result = q.wait(job_id, timeout_s=300)
    print(f"OK: {result.get('ok')}, Files: {result.get('files_created')}")
    print(f"Message: {result.get('message')}")
except TimeoutError:
    print(f"Job {job_id} timed out — NX bridge not running?")
```

### 2.5 各 Action 参数

| Action | 必需参数 | 可选参数 | 说明 |
|--------|---------|---------|------|
| `create_block_part` | `length_mm, width_mm, height_mm, out_prt` | `out_step` | 创建矩形块，保存 PRT |
| `create_block_with_hole` | `length_mm, width_mm, height_mm, hole_dia_mm, out_prt` | `hole_x, hole_z, out_step` | 带通孔的块 |
| `create_l_bracket` | `base_length, base_width, thickness, leg_height, out_prt` | `out_step` | L 形支架 |
| `create_stepped_block` | `base_length, base_width, base_height, top_length, top_width, top_height, out_prt` | `out_step` | 阶梯块 |
| `export_step` | `input_prt, out_step` | — | PRT→STEP |
| `import_step_as_prt` | `input_step, out_prt` | `out_step` | STEP→PRT (工业级齿轮路径) |

### 2.6 目录结构

```text
%HOME%\seekflow_workspace\nx_jobs\
├── pending/       ← 提交的 job (*.json)
├── running/       ← 正在处理的 job + heartbeat.json
├── done/          ← 完成的 job (*.result.json)
├── failed/        ← 失败的 job (*.result.json)
└── STOP           ← 创建此文件停止 bridge
```

### 2.7 注意事项

- NX 12.0 的 Python 版本是 3.6，bridge bootstrap 不使用 f-string 和 `from __future__ import annotations`
- `NXOpen` 只能在 NX 内部导入；bridge 文件不能在外部 Python 运行
- NX 启动需要 1-2 分钟，耐心等待 heartbeat 更新
- 如果 STEP 导出失败 ("preference does not exist")，是 NX 12.0 配置问题，不影响 PRT 创建

---

## 3. ANSYS 18.1 APDL 批处理

### 3.1 前置条件

```text
- ANSYS 18.1 安装
- ansys181.exe 路径: D:\ANSYS181\ANSYS Inc\v181\ANSYS\bin\winx64\ansys181.exe

环境变量:
  ANSYS181_DIR = D:\ANSYS181\ANSYS Inc\v181\ANSYS
  ANSYS_SYSDIR = winx64
  ANSYS_SYSDIR32 = win32
```

### 3.2 运行 APDL 分析

```python
from pathlib import Path
from seekflow_engineering_tools.ansys.apdl_runner import AnsysAPDLRunner
from seekflow_engineering_tools.ansys.apdl_templates import (
    static_cantilever_beam_rect_apdl,
    plate_with_hole_tension_apdl,
    beam_thermal_apdl,
    cantilever_modal_apdl,
    buckling_column_apdl,
    bilinear_plastic_apdl,
)
from seekflow_engineering_tools.ansys.parsers import parse_result_summary

# 初始化
ansys_exe = Path(r"D:\ANSYS181\ANSYS Inc\v181\ANSYS\bin\winx64\ansys181.exe")
runner = AnsysAPDLRunner(
    ansys_exe=ansys_exe,
    workspace_root=Path("./ansys_output"),
    default_timeout_s=120,
)

# 1. 静力分析: 悬臂梁
apdl = static_cantilever_beam_rect_apdl(
    length_mm=200, width_mm=20, height_mm=20,
    force_n=1000, element_size_mm=20.0,
)
inp = Path("beam.inp")
inp.write_text(apdl, encoding="utf-8")
result = runner.run_apdl_file(inp, Path("./beam_out"), "beam_job", memory_mb=256)
print(f"RC={result['returncode']}, elapsed={result['elapsed_s']}s, error={result['has_error']}")

# 2. 应力集中: 带孔板
apdl = plate_with_hole_tension_apdl(
    plate_width_mm=200, plate_height_mm=100, plate_thickness_mm=10,
    hole_diameter_mm=20, tensile_stress_mpa=100, element_size_mm=10.0,
)

# 3. 稳态热分析
apdl = beam_thermal_apdl(200, 20, 20, element_size_mm=10.0)

# 4. 模态分析
apdl = cantilever_modal_apdl(200, 20, 20, n_modes=5, element_size_mm=20.0)

# 5. 屈曲分析
apdl = buckling_column_apdl(500, 20, 20, element_size_mm=10.0)

# 6. 双线性塑性
apdl = bilinear_plastic_apdl(100, 10, 10, displacement_mm=5, element_size_mm=10.0)
```

### 3.3 解析结果

```python
from seekflow_engineering_tools.ansys.parsers import parse_result_summary

# 读取 ANSYS 输出文件
out_file = Path("./beam_out/beam_job.out")
metrics = parse_result_summary(out_file)

# 各分析类型的返回值:
# Static:    {"max_displacement_mm": float}
# Plate:     {"max_displacement_mm": float, "max_stress_mpa": float, "stress_concentration_kt": float}
# Thermal:   {"tmin_c": float, "tmax_c": float, "tmid_c": float}
# Modal:     {"modal_frequencies_hz": [f1, f2, ...], "mode_1_hz": f1, ...}
# Buckling:  {"buckling_load_factor": float, "pcr_n": float}
# Plastic:   {"max_plastic_strain": float, "tip_displacement_mm": float}
```

### 3.4 内存管理

```text
ANSYS 默认请求约 2GB 内存。
使用 memory_mb 参数控制:

runner.run_apdl_file(inp, out_dir, "job", memory_mb=256)   # 256MB
runner.run_apdl_file(inp, out_dir, "job", memory_mb=512)   # 512MB
```

如果 `memory_mb` 值过大导致 `FATAL: memory not available`，减小该值。

### 3.5 输出文件

每个分析在 `job_dir/` 下生成:

```text
beam_job.out      ← 主输出 (含 *VWRITE 结果)
beam_job.err      ← 错误日志
beam_job.log      ← ANSYS 日志
beam_job.db       ← 数据库
beam_job.rst      ← 结果文件
result_summary.txt ← 结构化结果 (由 /OUTPUT 指令生成)
```

### 3.6 错误检测

```python
result = runner.run_apdl_file(inp, job_dir, "job", memory_mb=256)

# has_error 为 True 表示:
#   - returncode != 0
#   - 输出中有 "*** ERROR ***"
#   - stderr 中有 "ERROR"
#   - .err 文件中有 "FATAL"

if result["has_error"]:
    # 检查错误详情
    err_file = job_dir / "job.err"
    if err_file.exists():
        print(err_file.read_text(errors="ignore")[:500])
```

---

## 4. 统一构建入口 (Build Planner)

### 4.1 架构概览

```
CAD-IR (PrimitiveFeature or RecipeFeature)
  → engineering_validate_cad_ir (normalize + rewrite + check)
  → engineering_build_cad_model (route by backend + strategy)
    ├─ cadquery: build_cadquery_from_cad_ir → STEP + metadata
    ├─ solidworks2025:
    │   ├─ recipe (box/flanged_hub): build_solidworks_direct_recipe
    │   └─ primitive (gear): CadQuery→STEP→SW import→SLDPRT
    └─ nx12:
        ├─ recipe (box/block+hole/l_bracket/stepped_block): build_nx_direct_recipe
        └─ primitive (gear): CadQuery→STEP→NX import→PRT
```

### 4.2 Primitive Strategy

```python
from seekflow_engineering_tools.capabilities.registry import get_primitive_strategy

# cadquery 原生支持 CQ_Gears 齿轮
assert get_primitive_strategy("cadquery", "involute_spur_gear") == "native_cadquery_primitive"

# SolidWorks/NX 通过 STEP 导入
assert get_primitive_strategy("solidworks2025", "involute_spur_gear") == "cadquery_step_import"
assert get_primitive_strategy("nx12", "involute_spur_gear") == "cadquery_step_import"
```

### 4.3 工业级齿轮完整链条

```python
from seekflow_engineering_tools.natural_language.backend_builders import (
    build_canonical_step_with_cadquery,
    build_solidworks_from_canonical_step,
    build_nx_from_canonical_step,
)
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.ir.cad import CADPartSpec
from pathlib import Path

config = EngineeringToolsConfig(workspace_root=Path("./workspace"), allow_overwrite=True)

# 定义齿轮 CAD-IR
spec = CADPartSpec.model_validate({
    "name": "industrial_gear",
    "units": "mm",
    "target_backend": ["solidworks2025"],
    "features": [{
        "id": "gear1",
        "type": "primitive",
        "primitive_name": "involute_spur_gear",
        "parameters": {
            "module_mm": 2.0, "teeth": 24,
            "pressure_angle_deg": 20.0, "face_width_mm": 15.0,
            "bore_dia_mm": 10.0, "quality_grade": "industrial_brep",
        },
    }],
    "validation": {"expected_body_count": 1, "tolerance_mm": 0.5},
})

# 方式1: CadQuery 原生构建
result = build_canonical_step_with_cadquery(
    spec, config, out_step="models/gear.step"
)

# 方式2: CadQuery → SolidWorks import
result = build_solidworks_from_canonical_step(
    spec, config,
    out_step="models/gear.step",
    out_native="models/gear.SLDPRT",
)

# 方式3: CadQuery → NX import
result = build_nx_from_canonical_step(
    spec, config,
    out_step="models/gear.step",
    out_native="models/gear.prt",
)
```

### 4.4 快速参考: CAD-IR 格式

```json
{
  "name": "part_name",
  "units": "mm",
  "target_backend": ["cadquery"],
  "features": [
    {
      "id": "feat1",
      "type": "recipe",
      "recipe_name": "box",
      "parameters": {"length_mm": 100, "width_mm": 50, "height_mm": 25}
    },
    {
      "id": "gear1",
      "type": "primitive",
      "primitive_name": "involute_spur_gear",
      "parameters": {
        "module_mm": 2.0, "teeth": 24,
        "pressure_angle_deg": 20.0, "face_width_mm": 15.0,
        "bore_dia_mm": 10.0,
        "quality_grade": "industrial_brep"
      },
      "operation": "new_body"
    }
  ],
  "validation": {
    "expected_body_count": 1,
    "tolerance_mm": 0.5,
    "expected_kernel": "cq_gears"
  }
}
```

### 4.5 运行完整 Demo

```bash
cd integrations/engineering_tools

# 全后端工业级 demo
python demo_industrial_full.py --output E:\auto_detection_process\demo_output

# CI 验收: 单个 case
python demo_full_chain.py --case involute_spur_gear --backend cadquery --json-report reports/gear.json

# CI 验收: 全部 case
python demo_full_chain.py --case all --backend cadquery --json-report reports/full_chain.json

# SW/NX 齿轮 (需要 --allow-step-import)
python demo_full_chain.py --case involute_spur_gear --backend solidworks2025 --allow-step-import
python demo_full_chain.py --case involute_spur_gear --backend nx12 --allow-step-import
```

### 4.6 各后端的路径总结

```
CadQuery:
  → CQ_Gears (齿轮) / recipe generators
  → build_cadquery_from_cad_ir()
  → STEP + metadata.json

SolidWorks:
  简单零件: recipe → create_extruded_box / create_flanged_hub → SLDPRT
  齿轮:     CQ_Gears → CadQuery STEP → LoadFile2 → SaveAs3 → SLDPRT

NX:
  简单零件: job queue → create_block_part / etc → PRT
  齿轮:     CQ_Gears → CadQuery STEP → import_step_as_prt → PRT

ANSYS:
  APDL template → ansys181.exe -b -m 256 → .out + result_summary.txt
```
