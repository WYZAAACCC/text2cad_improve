# SeekFlow Engineering Tools — 架构文档

> 版本：v0.1.0 | 日期：2026-05-28 | 面向：代码审核人员

---

## 一、项目概述

`seekflow-engineering-tools` 是 SeekFlow 平台下的**工业级工程工具集成包**，提供从自然语言到 CAD/CAE 模型的完整链路。支持 CadQuery（确定性 Python 3D 建模）、SolidWorks 2025（COM 自动化）、Siemens NX 12.0（Job Queue Bridge）、ANSYS 18.1（APDL 批处理）四个后端。

**核心设计理念**：
- **CAD-IR 中间表示**：统一的 JSON/Pydantic 模型作为所有后端的前端接口
- **Primitive 体系**：工程语义化的确定性参数化几何单元，禁止 LLM 直接生成 CAD 代码
- **Fail-Closed 策略**：所有异常路径必须明确失败，不允许 silent fallback
- **Metadata Sidecar**：每个 Primitive 构建输出附带完整元数据 JSON 文件

---

## 二、目录结构

```
integrations/engineering_tools/
├── demo_full_chain.py              # CI 验收脚本（全链路集成测试）
├── pyproject.toml                  # 项目配置与依赖
├── tests/                          # 349 个测试（当前）
├── demo_output/                    # 输出目录
├── .claude/skills/                 # Skill 合约文件
│   └── turbomachinery-cad-ir/SKILL.md
└── src/seekflow_engineering_tools/
    ├── __init__.py                 # 包入口
    ├── config.py                   # EngineeringToolsConfig 统一配置
    ├── registry.py                 # 顶层工具注册与 Agent 工厂
    │
    ├── ir/                         # 中间表示层（IR）
    │   ├── cad.py                  # CAD-IR：CADPartSpec, PrimitiveFeature 等
    │   ├── cae.py                  # CAE-IR：CAEJobSpec
    │   ├── primitive.py            # PrimitiveFeature Pydantic 模型
    │   ├── validation.py           # IR 级验证
    │   └── defaults.py             # 默认容差值
    │
    ├── geometry_primitives/        # 几何 Primitive 体系（核心）
    │   ├── base.py                 # PrimitiveDefinition / PrimitiveParameter
    │   ├── registry.py             # 全局 Primitive 注册表 + 参数标准化
    │   ├── graph.py                # Primitive 依赖图（DAG）
    │   ├── gears/                  # 齿轮 Primitive（已实现）
    │   │   ├── models.py           # involute_spur_gear 定义
    │   │   ├── standards.py        # ISO 53 / DIN 867 标准计算
    │   │   ├── validator.py        # 齿轮参数验证器
    │   │   ├── cq_gears_adapter.py # CQ_Gears 内核适配器
    │   │   ├── cadquery_fallback.py# 视觉回落内核
    │   │   └── metadata.py         # 元数据读写
    │   └── turbomachinery/         # 涡轮机械 Primitive（已实现）
    │       ├── models.py           # axisymmetric_turbine_disk 定义（~70 参数）
    │       ├── validator.py        # 涡轮盘参数验证器
    │       ├── axisymmetric_turbine_disk.py  # v6 几何内核（~730 行）
    │       └── metadata.py         # 涡轮盘元数据验证器
    │
    ├── mechanical_validation/      # 力学验证体系
    │   ├── common.py               # 验证器注册表 + dispatch
    │   ├── gear_validation.py      # 齿轮验证器
    │   ├── turbomachinery_validation.py  # 涡轮盘验证器
    │   ├── primitive_metadata.py   # 通用 metadata v1 验证
    │   └── topology_validation.py  # 拓扑验证（body count/bbox）
    │
    ├── cadquery_backend/           # CadQuery 后端
    │   ├── compiler.py             # CAD-IR → Python 脚本编译器
    │   ├── primitive_compiler.py   # Primitive 编译器注册表
    │   ├── builder.py              # 构建管线（编译→执行→验证→元数据）
    │   ├── recipes.py              # Recipe 代码生成器（10 个）
    │   ├── inspector.py            # STEP 检查器
    │   └── tools.py                # SeekFlow Tool 注册
    │
    ├── capabilities/               # 能力注册表
    │   └── registry.py             # 4 后端的 recipes/primitives/strategies
    │
    ├── recipes/                    # Recipe 系统
    │   ├── base.py                 # RecipeDefinition / RecipeParameter
    │   ├── mechanical.py           # 13 个机械 recipe 定义
    │   └── registry.py             # Recipe 注册表 + 参数校验
    │
    ├── solidworks/                 # SolidWorks 2025 COM 自动化
    │   ├── com_client.py           # COM 客户端（~960 行）
    │   └── tools.py                # 5 个 SeekFlow Tool
    │
    ├── nx/                         # NX 12.0 Job Queue Bridge
    │   ├── job_queue.py            # 文件队列管理器
    │   ├── nx_bridge_bootstrap.py  # NXOpen Journal
    │   └── tools.py                # 7 个 SeekFlow Tool
    │
    ├── ansys/                      # ANSYS 18.1 APDL 批处理
    │   ├── apdl_templates.py       # 6 个 APDL 模板生成器
    │   ├── apdl_runner.py          # 子进程执行器
    │   ├── template_registry.py    # 模板注册表
    │   ├── parsers.py              # 结果解析器
    │   └── tools.py                # 4 个 SeekFlow Tool
    │
    ├── inspection/                 # 几何检查
    ├── repair/                     # 自动修复循环
    ├── natural_language/           # NL → CAD-IR 翻译层
    └── common/                     # 公共工具（路径/模型/验证）
```

---

## 三、核心数据流

```
用户自然语言
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ NL → CAD-IR 翻译（natural_language/）                │
│  - 参数提取 → 歧义检测 → 默认值填充                    │
│  - 废弃 recipe → primitive 自动重写                    │
└──────────────────────────────────────────────────────┘
    │
    ▼ CAD-IR (CADPartSpec)
┌──────────────────────────────────────────────────────┐
│ 验证管线（engineering_validate_cad_ir）               │
│  1. schema 验证                                       │
│  2. 语义验证                                          │
│  3. 参数标准化（normalize_primitive_parameters）       │
│     ├─ 类型转换 (float/int/str/bool)                   │
│     ├─ min/max 约束                                   │
│     └─ primitive-specific validator                   │
│  4. 后端能力检查                                      │
└──────────────────────────────────────────────────────┘
    │
    ▼ 标准化 CAD-IR
┌──────────────────────────────────────────────────────┐
│ 构建管线（engineering_build_cad_model）               │
│  ┌─ choose_backend → 选择后端 + 策略                  │
│  │                                                    │
│  ├─ cadquery: 直接本地构建                            │
│  │   ├─ compile: CAD-IR → CadQuery Python 脚本        │
│  │   │   ├─ recipe: 通过 CADQUERY_RECIPE_GENERATORS   │
│  │   │   └─ primitive: 通过 PRIMITIVE_COMPILERS       │
│  │   ├─ execute: subprocess 运行脚本                  │
│  │   ├─ verify: 检查 STEP 文件                        │
│  │   ├─ inspect: CadQuery 导入 STEP 测量              │
│  │   ├─ validate: 对比 CAD-IR 期望值                  │
│  │   ├─ metadata sidecar: 验证 .metadata.json         │
│  │   └─ mechanical: 调度 primitive-specific 验证器    │
│  │                                                    │
│  ├─ solidworks2025/nx12 + primitive:                  │
│  │   └─ 先 cadquery → canonical STEP                  │
│  │     → 验证通过后 → SW/NX import STEP               │
│  │                                                    │
│  └─ solidworks2025/nx12 + recipe: 直接 native 构建    │
└──────────────────────────────────────────────────────┘
    │
    ▼ 输出：STEP + 原生格式 + metadata.json
```

---

## 四、Primitive 体系架构

### 4.1 注册表层级

```
PrimitiveDefinition (base.py)
    │
    ▼
PRIMITIVE_REGISTRY (registry.py)
    │ 由 PRIMITIVE_FAMILY_MODULES 自动加载
    ├── involute_spur_gear (gears/models.py)
    └── axisymmetric_turbine_disk (turbomachinery/models.py)
    │
    ▼ 各子系统注册表（独立，不耦合）
├── PRIMITIVE_COMPILERS (cadquery_backend/primitive_compiler.py)
├── PRIMITIVE_MECHANICAL_VALIDATORS (mechanical_validation/common.py)
└── CAPABILITIES (capabilities/registry.py)
```

### 4.2 Primitive 生命周期

```
注册 (models.py)
  → 参数标准化 (registry.normalize_primitive_parameters)
    → 类型转换 + min/max + default
    → primitive-specific validator (validator.py)
  → 编译 (primitive_compiler.py)
    → 生成 Python 脚本调用 deterministic kernel
  → 内核执行 (axisymmetric_turbine_disk.py / cq_gears_adapter.py)
    → 返回 CadQuery shape + metadata dict
  → 元数据完成 (.metadata.json sidecar)
  → 通用 metadata 验证 (primitive_metadata.validate_primitive_metadata_v1)
  → primitive-specific metadata 验证 (metadata.py)
  → 检查 (inspection/validation)
  → 力学验证 (mechanical_validation/)
  → 最终输出
```

### 4.3 现有 Primitives

| Primitive | 类别 | Kernel | 参数数 | 状态 |
|-----------|------|--------|--------|------|
| `involute_spur_gear` | gears | cq_gears / cadquery_visual_fallback | 12 | v0 稳定 |
| `axisymmetric_turbine_disk` | turbomachinery | cadquery_turbine_disk_reference_v6 | ~70 | v6 稳定 |

### 4.4 axisymmetric_turbine_disk 版本演进

| 版本 | Kernel | 关键变更 |
|------|--------|----------|
| v0 | cadquery_axisymmetric_revolve_v0 | 基础 revolve 盘体 + 孔环 |
| v2 | cadquery_turbine_disk_reference_v2 | 添加 cyclic rim slots (box union) |
| v3 | cadquery_turbine_disk_reference_v3 | side-groove → axial_through 方向 |
| v4 | cadquery_turbine_disk_reference_v4 | 窄口+内扩 lobe internal_socket profile |
| v5 | cadquery_turbine_disk_reference_v5 | 多级对称 fir-tree 多边形 profile (station-based) |
| **v6** | **cadquery_turbine_disk_reference_v6** | **拓扑清理：去重、短边过滤、面积验证、clean() 调用** |

---

## 五、策略与后端路由

### 5.1 Primitive Strategy

```
cadquery:
  involute_spur_gear       → native_cadquery_primitive
  axisymmetric_turbine_disk → native_cadquery_primitive

solidworks2025 / nx12:
  involute_spur_gear       → cadquery_step_import
  axisymmetric_turbine_disk → cadquery_step_import
```

**cadquery_step_import 流程**：
1. CadQuery 本地构建 → canonical STEP + metadata
2. 验证 CadQuery 构建结果、metadata、inspection、mechanical validation
3. 全部通过后 → SW/NX import STEP → 保存为原生格式

### 5.2 后端能力矩阵

| 后端 | Recipes | Primitives | 原生格式 | STEP |
|------|---------|------------|----------|------|
| cadquery | 8 | 2 | — | ✅ |
| solidworks2025 | 2 (box, flanged_hub) | 2 (via STEP import) | SLDPRT | ✅ |
| nx12 | 4 | 2 (via STEP import) | PRT | ✅ |
| ansys181 | — | — | — | — |

---

## 六、Validation 验证链

### 6.1 通用验证

| 阶段 | 模块 | 检查内容 |
|------|------|----------|
| IR Schema | `ir/validation.py` | CADPartSpec Pydantic 验证 |
| 参数标准化 | `geometry_primitives/registry.py` | 类型转换、min/max、default |
| Primitive 参数 | `validator.py` (per-primitive) | 几何一致性、安全约束 |
| Generic Metadata | `mechanical_validation/primitive_metadata.py` | kernel、parameters、warnings 格式 |
| Primitive Metadata | `metadata.py` (per-primitive) | 结构完整性、safety flags |
| 几何检查 | `inspection/validation.py` | bbox、body count、hole count |
| 力学验证 | `mechanical_validation/common.py` | Primitive-specific 最终验证 |

### 6.2 Fail-Closed 机制

- **未注册 primitive validator** → `primitive_mechanical_validator_missing` error → overall False
- **strategy is None** → `choose_backend` stage fail → 不允许 fallback
- **SolidWorks/NX 缺少 --allow-step-import** → `choose_backend` fail
- **metadata sidecar 缺失** → build fail
- **warnings 非 list/非 str** → metadata validation error
- **bool("False") = True 错误** → 已修复为严格 `_parse_bool`
- **Visual fallback 齿轮用于 industrial_brep** → hard fail

---

## 七、Metadata 体系

每个 Primitive 构建输出 `.metadata.json` sidecar 文件，结构：

```json
{
  "primitive_metadata": {
    "<primitive_name>": {
      "primitive": "axisymmetric_turbine_disk",
      "metadata_version": "primitive_metadata_v1",
      "kernel": "cadquery_turbine_disk_reference_v6",
      "geometry_family": "axisymmetric_base_with_clean_symmetric_fir_tree_slots",
      "parameters": { ... },
      "reference_dimensions": { ... },
      "warnings": [ ... ],
      "radial_zones": { ... },
      "axial_zones": { ... },
      "profile_points": [ ... ],
      "hole_patterns": [ ... ],
      "slot_generation": {
        "version": "rim_slot_v6_clean_symmetric_polygon",
        "profile_generation_method": "single_clean_polygon",
        "box_union_used": false,
        "is_mirror_symmetric": true,
        "profile_area_mm2": 123.45,
        "stage_count": 3,
        "stage_stations": [ ... ]
      },
      "rim_features": { ... },
      "visual_fidelity": {
        "contains_clean_symmetric_fir_tree_slots": true,
        "contains_box_union_fir_tree_slots": false,
        "contains_real_blade_attachment": false
      },
      "safety": {
        "non_flight_reference_only": true,
        "not_airworthy": true,
        "not_certified": true,
        "not_for_manufacturing": true,
        "not_for_installation": true,
        "no_structural_validation": true,
        "no_life_prediction": true
      }
    }
  },
  "build_warnings": [ ... ],
  "validation": {
    "inspection_validation": { ... },
    "mechanical_validation": { ... }
  }
}
```

---

## 八、测试架构

### 8.1 测试文件分类（当前 349 个测试）

| 类别 | 测试文件 | 测试数 |
|------|----------|--------|
| IR Schema | test_cad_ir_schema.py | ~10 |
| Registry | test_registry.py, test_recipe_registry.py, test_primitive_family_registry.py | ~30 |
| Capability | test_capability_registry.py, test_capability_registry_primitives.py | ~20 |
| CadQuery Backend | test_cadquery_backend.py, test_cadquery_builder_fail_closed.py | ~15 |
| Primitive 注册 | test_geometry_primitives_registry.py | ~5 |
| Primitive 编译 | test_primitive_compiler_registry.py | ~5 |
| 齿轮 Primitive | test_gear_metadata_sidecar.py, test_gear_validation.py, test_involute_spur_gear_*.py | ~30 |
| 涡轮盘 Primitive | test_axisymmetric_turbine_disk_*.py (7 files) | ~50 |
| 涡轮盘视觉 | test_turbine_disk_visual_features.py | ~6 |
| Metadata | test_primitive_metadata_v1.py, test_primitive_metadata_sidecar_generic.py | ~20 |
| 力学验证 | test_primitive_mechanical_validation_dispatch.py | ~10 |
| Demo | test_demo_full_chain_gear.py, test_demo_full_chain_generic_primitive.py, test_demo_full_chain_turbine_disk.py | ~15 |
| SW/NX Mock | test_solidworks_mock.py, test_nx_*.py | ~30 |
| ANSYS | test_ansys_*.py | ~15 |
| Bool 解析 | test_primitive_bool_normalization.py | ~5 |
| 其他 | test_registry.py, test_compileall.py, test_future_primitive_support_contract.py 等 | ~80 |

### 8.2 验收命令

```bash
cd integrations/engineering_tools

# 完整测试套件
python -m pytest tests -q

# 单测
python -m pytest tests/test_axisymmetric_turbine_disk_parameters.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_metadata.py -q

# Demo 验收
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery
python demo_full_chain.py --case axisymmetric_turbine_disk --backend solidworks2025 --allow-step-import
python demo_full_chain.py --case involute_spur_gear --backend cadquery
```

---

## 九、安全边界（不可违反）

1. **禁止 LLM 直接生成 CAD 代码** — 所有几何必须通过 deterministic kernel 生成
2. **禁止 SolidWorks COM/VBS/NXOpen/APDL 几何代码生成**
3. **禁止 flight-ready / airworthy / certified / manufacturing-ready / production-ready / installable 声明**
4. **所有 turbomachinery primitives 为 non-flight reference geometry only**
5. **SolidWorks / NX 只能 import canonical STEP**，不能重建几何
6. **所有异常路径 fail-closed**，不能 silent fallback
7. **所有 metadata / warnings / safety 必须明确声明 non-flight / not airworthy / not certified / not for manufacturing**

---

## 十、关键设计决策

| 决策 | 原因 |
|------|------|
| Primitive 独立于 Recipe | Primitive 是工程语义化单元，Recipe 是通用 CAD feature，两者有不同的验证链 |
| Primitive 通过 importlib 动态加载 | 新增 Primitive 只需在 family module 注册，不用改 registry 核心代码 |
| Compiler handler 只 dispatch 不内联几何 | 几何逻辑集中在 kernel 文件，compiler 只生成调用代码 |
| Metadata sidecar 独立于 STEP | 支持无 CAD 环境的 metadata 验证 |
| Mechanical validation 在 inspection 之后 | 先用几何测量验证基本形状，再用 primitive 特定规则验证 |
| SW/NX 通过 canonical STEP import | 确保 SW/NX 收到的是已验证的正确 STEP，而非依赖各自的重建逻辑 |
| Station-based polygon profile (v5+) | 消除 box-union cutter 的拓扑问题（自交、seam edges） |
| Clean polygon + dedup + area check (v6) | 彻底解决外缘 slot 的 sliver faces 和三角洞问题 |

---

## 十一、已知技术债务

1. **NX backend 依赖运行中的 NX Bridge** — 无 Bridge 时 job queue 超时返回 fail-closed
2. **SolidWorks backend 需要 Windows + pywin32** — COM 自动化环境依赖
3. **ANSYS 18.1 APDL 批处理** — 需要本地 ANSYS 安装，非容器化
4. **gear visual fallback** — 当 cq_gears 不可用时使用近似几何，非标准渐开线
5. **turbomachinery 仅 axisymmetric_turbine_disk 已实现** — `parametric_turbine_blade` 仍为 reserved name
6. **demo_full_chain 中 gear case 引用裁切 reference_dimensions** — 需统一使用 generic runner
