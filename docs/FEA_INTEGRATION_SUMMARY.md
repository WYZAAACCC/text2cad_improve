# Text-to-CAD + FEA 全流程集成总结

## 1. 用户需求

在 Text-to-CAD 前端生成涡轮盘 3D 模型后，直接在同一个界面中完成有限元分析：

1. **CAD 生成**：自然语言 prompt → 空间交互问答 → 3D 涡轮盘 (STEP + STL)
2. **FEA 参数设定**：材料、载荷（转速/温度）、边界条件（面选择）、网格密度 — 人工设定关键参数
3. **FEA 执行**：后端调用 ANSYS 18.1 APDL batch，前端轮询进度
4. **结果展示**：数值指标 (VMmax, 安全系数) + 2D 应力热力图 + 3D 应力场着色

## 2. 已实现的功能

### 2.1 后端 FEA API（5 个路由）

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/api/fea/templates` | 返回 7 个可用 ANSYS 模板 + 参数 schema |
| `POST` | `/api/fea/execute` | 提交参数 → 生成 APDL → 调用 ansys181.exe → 返回结果 |
| `GET` | `/api/fea/result/{task_id}` | 轮询 FEA 任务状态和结果 |
| `GET` | `/api/fea/regions/{model_id}` | 返回模型的命名区域定义 (bore, rim, web, hub faces + 旋转轴 + 中面) |
| `GET` | `/api/health` | 健康检查 (含 `fea_tasks` 计数) |

### 2.2 前端 FEA 交互

- **RightPanel 新增 FEA Tab**：属性/图层 | 数据集 | **FEA** 三个 Tab
- **FeaTab 面板**：
  - 模型选择下拉框（从场景中选 STEP 模型）
  - 参数输入：转速 (RPM)、轮缘温度 (°C)、轮毂温度 (°C)
  - 模板选择：涡轮盘(轴对称) / 悬臂梁(静态)
  - 运行按钮 + 进度显示
  - 结果展示：VMmax、安全系数、用时
  - 应力场热力图（Canvas 2D，jet colormap）
  - 3D 应力着色开关（按钮 → 工具栏同步）
  - 分析历史记录
- **Viewport3D 3D 应力着色**：
  - STL 顶点 (x,y,z) → 计算 (R,Z) → 匹配最近 ANSYS 节点 → jet colormap 着色
  - 工具栏 "🌡️ 应力开/关" 按钮

### 2.3 ANSYS 模板

| 模板名 | 分析类型 | 说明 |
|--------|---------|------|
| `turbine_disc_rotational_thermal` | 轴对称热-结构 | 涡轮盘 2D PLANE183 轴对称模型，离心力+温度场，输出 VM/径向/周向应力 + nodal_stress.csv |
| `static_cantilever_beam_rect` | 静态结构 | SOLID185 悬臂梁 |
| `plate_with_hole_tension` | 静态结构 | 带孔板应力集中 |
| `beam_thermal` | 稳态热 | SOLID70 温度梯度 |
| `cantilever_modal` | 模态 | SOLID185 固有频率 |
| `buckling_column` | 屈曲 | BEAM188 Euler 屈曲 |
| `bilinear_plastic` | 双线性塑性 | SOLID185 塑性变形 |

## 3. ANSYS 调用方式

### 3.1 前置条件

- ANSYS 18.1 安装于 `D:\ANSYS181\ANSYS Inc\v181\`
- 可执行文件: `ansys/bin/winx64/ansys181.exe`
- 环境变量: `ANSYS181_EXE=D:/ANSYS181/ANSYS Inc/v181/ansys/bin/winx64/ansys181.exe`

### 3.2 API 调用

**直接执行 (推荐):**
```bash
curl -X POST "http://127.0.0.1:8080/api/fea/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "template_name": "turbine_disc_rotational_thermal",
    "parameters": {"rpm": 5000, "temp_rim_c": 650, "temp_bore_c": 500},
    "jobname": "my_turbine_analysis"
  }'
# 返回: {"task_id": "d8356ac50b7f4707"}
```

**轮询结果:**
```bash
curl "http://127.0.0.1:8080/api/fea/result/d8356ac50b7f4707"
# {
#   "status": "completed",
#   "result": {
#     "ok": true,
#     "elapsed_s": 5.0,
#     "metrics": {
#       "max_von_mises_mpa": 1077.1,
#       "max_radial_stress_mpa": 11187.4,
#       "min_safety_factor": 0.84
#     },
#     "stress_field": [
#       {"r_mm": 60.0, "z_mm": -38.0, "seqv_mpa": 0.8, ...},
#       ...
#     ]
#   }
# }
```

### 3.3 Python 调用

```python
import os, json
os.environ['ANSYS181_EXE'] = r'D:\ANSYS181\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe'

from pathlib import Path
from seekflow_engineering_tools.ansys.apdl_runner import AnsysAPDLRunner
from seekflow_engineering_tools.ansys.apdl_templates import render_template
from seekflow_engineering_tools.ansys.template_registry import validate_template_parameters

# 1. 验证参数
params = validate_template_parameters("turbine_disc_rotational_thermal", {
    "rpm": 5000, "temp_rim_c": 650, "temp_bore_c": 500
})

# 2. 生成 APDL
apdl = render_template("turbine_disc_rotational_thermal", **params)

# 3. 运行 ANSYS
runner = AnsysAPDLRunner(
    ansys_exe=Path(r"D:\ANSYS181\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe"),
    workspace_root=Path("./ansys_jobs"),
    default_timeout_s=600
)
result = runner.run_apdl_file(
    input_file=Path("input.inp"),
    job_dir=Path("./ansys_jobs/my_job"),
    jobname="my_job"
)

# 4. 解析结果
from seekflow_engineering_tools.ansys.parsers import parse_result_summary, parse_nodal_stress
metrics = parse_result_summary(Path("./ansys_jobs/my_job/result_summary.txt"))
stress = parse_nodal_stress(Path("./ansys_jobs/my_job/nodal_stress.csv"))
```

### 3.4 ANSYS 命令行直接调用

```bash
# 生成 APDL 后，可直接用 ansys181.exe 运行:
"D:/ANSYS181/ANSYS Inc/v181/ansys/bin/winx64/ansys181.exe" \
  -b -m 512 -i input.inp -o output.out -j jobname
```

## 4. 涡轮盘 FEA 模板参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `rpm` | float | 15000 | 转速 (RPM) |
| `temp_rim_c` | float | 650 | 轮缘温度 (°C) |
| `temp_bore_c` | float | 500 | 轮毂温度 (°C) |
| `young_rim_mpa` | float | 150000 | 轮缘杨氏模量 (MPa) |
| `young_bore_mpa` | float | 175000 | 轮毂杨氏模量 (MPa) |
| `yield_mpa_650c` | float | 900 | 屈服强度 (MPa) |
| `density_tonnemm3` | float | 8.24e-9 | 密度 (tonne/mm³) |
| `poisson` | float | 0.3 | 泊松比 |
| `alpha` | float | 1.45e-5 | 热膨胀系数 (/°C) |
| `element_size_mm` | float | 5.0 | 网格尺寸 (mm) |

## 5. 修改文件清单

| 文件 | 改动 |
|------|------|
| `app/text-to-cad/server/main.py` | 新增 5 个 FEA routes |
| `app/text-to-cad/server/fea_models.py` | **新建** FEA Pydantic 模型 |
| `app/text-to-cad/server/fea_pipeline.py` | **新建** FEA pipeline (执行/区域定义) |
| `app/text-to-cad/src/api.ts` | 新增 FEA API 函数 |
| `app/text-to-cad/src/types.ts` | 新增 FEA 类型定义 |
| `app/text-to-cad/src/store.ts` | FEA 状态 + actions + stressColoring |
| `app/text-to-cad/src/components/RightPanel.tsx` | 新增 FEA Tab |
| `app/text-to-cad/src/components/FeaTab.tsx` | **新建** FEA 面板 |
| `app/text-to-cad/src/components/StressHeatmap.tsx` | **新建** Canvas 2D 热力图 |
| `app/text-to-cad/src/components/Viewport3D.tsx` | STLGeometry 3D 应力着色 |
| `integrations/.../ansys/apdl_templates.py` | 新增 turbine_disc 模板 + nodal CSV 输出 |
| `integrations/.../ansys/parsers.py` | 新增 `parse_nodal_stress()` |
| `integrations/.../ansys/template_registry.py` | 注册 turbine_disc 模板 |
| `integrations/.../ansys/tools.py` | 注册 turbine_disc schema |

## 6. 验证结果

| 测试 | RPM | VMmax (MPa) | 安全系数 | 应力场点数 |
|------|-----|------------|---------|-----------|
| API 直接调用 | 5000 | 1077 | 0.84 | 2065 |
| 前端完整流程 | 5000 | 1077 | 0.84 | 2065 |

## 7. 后续规划

- Phase B: LLM 问答式 FEA 参数设定 (FeaModal)
- Phase B: 3D 面高亮联动 (dropdown hover → 3D 面对应高亮)
- Phase C: 应力场动画 / 等值面 / 剖面图
- ANSYS 模板扩展: 3D 扇区模型、接触分析、疲劳分析
