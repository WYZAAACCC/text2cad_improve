# 系统状态报告

> 评估日期：2026-09-10
> 代码基线：`606ab55`（2026-09-09）
> 运行环境：`.conda/python.exe`（Python 3.11.9 / OCP 7.8.1.1 / cadquery 2.7.0 / pytest 9.0.3）
> 用途：交接与状态更新。

**本文档取代** `PERSISTENT_TOPOLOGY_NAMING_STATUS.md` 与 `PERSISTENT_TOPOLOGY_NAMING_GAPS.md`。
那两份文档停留在 `96a7db2`（2026-08-17），其缺口判断与测试数字均已过期，会主动误导接手人（详见 §5.4）。
前者已于 2026-09-10 改为指向本文档的短跳转，后者已删除。

---

## 0. 摘要

核心引擎与持久化拓扑命名**已成熟且实测全绿**（320 passed / 0 failed）。
仿真侧代码齐全、各有一次真实求解器成功记录，但**尚未接线进 CAD 主流水线**。
实验数据完整，但与论文声称之间存在**必须披露的口径差**。

三条结论：

1. **拓扑命名是全项目最扎实的一块**，且比文档记录的完成度高得多。
2. **「agent 自动仿真」目前名不副实**——框架具备，但 CFD 主链路的 LLM 未启用。
3. **今天（09-10）的全部成果只存在于工作区**，未提交、未纳入版本控制。

---

## 1. 系统全景

系统由四层叠加而成：

| 层 | 位置 | 规模 | 作用 |
|---|---|---|---|
| 基础设施 | `src/seekflow/` | 119 py | SeekFlow v0.3.7，DeepSeek 原生 agent 安全运行时（策略引擎 / 沙箱 / 缓存 / 审计） |
| 产品原型 | `app/text-to-cad/` | React + Three.js 前端，FastAPI `server/main.py` | 文本 → CAD 的 Web 应用 |
| CAD 内核 | `integrations/engineering_tools/` | 670 py | 生成引擎：IR / validation / repair / topology·ocaf |
| 仿真 | `integrations/cfd/` + `_structural_experiment/` | — | CFD 与结构分析，agent 驱动 |

另有论文实验区 `_main_experiment/`（53 py）、`_param_experiment/`（108 py），以及根目录 72 个临时 `_*.py` 脚本（多为模型对比残留：`_test_qwen_*`、`_test_minimax_*`、`_test_glm_*`）。

### 1.1 三条生成路径

| 路径 | 位置 | 驱动 | 用途 |
|---|---|---|---|
| A 生产 Web | `app/text-to-cad/server/main.py` → `_run_pipeline()` | LLM / Agent | 真实产品链路 |
| B 论文主实验 | `_main_experiment/pipeline.py` → `run_experiment_task()` | LLM / Agent（可切模板基线） | 40 任务 × 10 种子基准 |
| C 确定性数据集 | `_param_experiment/` | **纯确定性代码，不调 LLM** | 32 族 D01–D32 数据集采集 |

三条路径都调用同一个引擎 `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/`。

### 1.2 两条仿真路径

| 子系统 | 位置 | 求解器 | 真实成功记录 |
|---|---|---|---|
| CFD | `integrations/cfd/`（包 `seekflow_cfd`）+ `_cfd_experiment/`（Worker） | Fluent 18.1 TUI journal 子进程 | **D01 一次** |
| 结构 | `_structural_experiment/`（脚本集，非包） | `ansys181.exe -b` APDL batch | **D19 一次** |

全仓**没有** `pymapdl` / `pyfluent` 的真实 import——这是正确的，ANSYS 18.1 只支持 APDL batch（见 `integrations/engineering_tools/INTEGRATION_ARCHITECTURE.md`）。

### 1.3 唯一的接缝

`generative_cad/ir/raw.py:112-137` 定义了两个把三线扣在一起的模型：

```python
class RawSelectionSpec   # selection_id / component_id / role_key / entity_kind / cardinality
class RawCaeBinding      # binding_id → selection_id + analysis_role("load_face"/"constraint_surface"/…)
```

`CanonicalGcadDocument` 携带 `selections: list[RawSelectionSpec]` 与 `cae_bindings: list[RawCaeBinding]`。
语义：LLM 在 IR 里声明「要哪个面」→ OCAF 让它跨 revision 稳定 → CAE 按 `analysis_role` 绑定载荷。

**设计已就绪，但装配代码缺失**（详见 §4.3）。

---

## 2. Agent 生成系统

状态：**成熟**，主要风险是双链路代码重复。

### 2.1 主链路

```
task prompt + normalized_params
  → pipeline._run_agentic_l2
      L1 路由      LLM 判 route_decision ∈ {generative_cad_ir, deterministic_primitive, unsupported}
      Agent A      需求 → 骨架 + profiles(params)          agentic_l2.py:_call_design_with_tools()
      Agent B      逐轮廓 params → 沙箱通用工具 → points    agentic_l2.py:_call_profile_with_tools()
      assemble     骨架 + points → RawGcadDocument          agentic_l2.py:assemble()
      repair loop  validation/runtime 错误 → 补丁
      MCP 门       6 项 CORE_SUBSET 质量门
  → STEP + BRep + STL + metadata.json + canonical_ir.json
  → metrics（唯一读 golden 的环节）
```

核心文件 `app/text-to-cad/server/agentic_l2.py`，**116 KB 单文件**。

### 2.2 质量机制

**四层修复环**（比我最初估计的深）：

| 层 | 位置 | 策略 |
|---|---|---|
| L1 路由重试 | `main.py` | `for attempt in range(4)` + `sleep(4)` |
| Agent B 轮廓重试 | `agentic_l2.py` | `for _attempt in range(3)`，不变式校验失败 → 反馈重试 |
| 内层 generation loop | `repair_kernel/orchestrator.py:run_generation_loop` | validation + runtime 双环；确定性 repair → LLM validation repair → runtime → 失败分类 → LLM runtime patch → **完整重验证 → commit → 用新 canonical 重跑 runtime** |
| 外层工程反馈环 | `_main_experiment/pipeline.py:_run_outer_feedback_loop` | MCP 门失败 → LLM 出 `RepairPatchV2` → 重跑，预算与内层共享 |

设计上值得注意的三点：

- **修复验收是字典序严格改善**：`QualityVector{error_count, warning_count, new_issue_count, blocked_stage_rank}` 必须严格变好才接受，否则回滚。`new_issue_count` 专门防「修好 2 个旧错、引入 1 个新错」被接受。
- **`allow_degradation_change=False`**（`repair_kernel/config.py`）——LLM 不允许用降级掩盖失败。
- **被 MCP 门拒的任务直接跳过 STEP 导出**，不产生「看起来成功」的产物。

**一致性 gate 密度**：生成前 5 类轮廓不变式（含 `_is_mirror_of` 镜像对称、逐齿 crest/plat/under/conn 顺序）→ IR 校验 22 模块（`validation/`）→ 运行时后置校验（`geometry_postcheck` / `semantic_postcheck` / `spatial_audit`）→ MCP 门 6 项核心子集。

### 2.3 生成完整性

`GENERATION_INTEGRITY_AUDIT.md` 已确认**生成链路完全不读 golden**（Agent A/B、沙箱、assemble、fillet 重建、repair loop、MCP 门逐环节核查）。golden 只在评估期（`metrics.semantics` / `metrics.geometry` / 冒烟脚本）被读取。

已修复的唯一真实泄漏：`fr_mm`（榫槽圆角比例）曾藏在 `normalized_params` 里未进 prompt，却被 harness 用来算 fillet 半径。现已作为显式设计参数写入 prompt。

四批实验中发现并修复的问题全部记录在 `GENERATION_INTEGRITY_AUDIT.md`，最终 T01–T30 × 各种子 100/100 通过。

### 2.4 缺口与风险

| 项 | 说明 |
|---|---|
| **双链路代码重复** | `main.py:_run_pipeline` 与 `_main_experiment/pipeline.py:run_experiment_task` 在 L1 路由、validation 落盘、MCP 门大量重复，但 prompt 注入不同（B 有 `explicit_req` / `normalized_params`，A 只有 `_append_parametric_block`）。**改一处必须同步另一处。** |
| **跨目录隐式耦合** | `agentic_l2.py` 被 `_main_experiment/pipeline.py:70` 用 `sys.path.insert` + `import agentic_l2` 直接导入，无包结构，重构风险高。 |

---

## 3. 持久化拓扑命名

状态：**全项目最扎实的一块**。实测 320 passed / 0 failed。

### 3.1 数据流

```
tracked_ops/*  ──OCCT History: Generated/Modified/IsRemoved──▶ LiveEvolutionBatch
      │
writer.py (TopologyNamingWriter) ──▶ OCAF 固定 Tag 树（TNaming_Builder）
      │
label_index.py (StableLabelIndex) ──▶ 「业务 key → TagPath」稳定映射
      │
selection_service.py (PersistentSelectionService) ──▶ TNaming_Selector 创建/求解
      │
pipeline/run.py:_run_ocaf_write_and_save() ──▶ IR selection → OCAF 选择 → CAE preflight → 子进程 verify
```

核心身份原语（`topology/ocaf/models.py`）：`SourceEntityRef` / `RelationKey` / `FaceRoleSpec` / `EdgeRoleSpec`。

`tracked_ops/` 共 11 个文件：`extrude` / `revolve` / `fillet` / `chamfer` / `boolean` / `offset_sweep`(shell·sweep·loft) / `pattern` / `unify` / `mirror` / `_carry`。

### 3.2 实测结果

```
.conda/python.exe -m pytest integrations/engineering_tools/tests/generative_cad/topology/ocaf/ -v
→ 320 passed, 5 warnings in 290.70s   (exit 0)
```

0 skipped / 0 xfail / 0 deselected。5 个 warning 全是同一条无害告警 `compute_bbox_mm: geometry inspection failed`。

C++ 原生 fixture 5 个绕过 pytest 直跑，全部 returncode=0：
`ocaf_smoke` / `tnaming_smoke` / `edge_lineage` / `edge_boolean` / `full_edge_boolean`。

> ⚠️ 该结果是**带工作区未提交改动**跑出来的，见 §6.1。

### 3.3 缺口项真实完成度

两份旧文档的判断**全部过期**。逐项对照：

| 项 | 旧文档说 | 代码实际 | 结论 |
|---|---|---|---|
| **P1-1** EDGE relation 迁移 | 未做 | `writer.py:300-307` 已把 FACE **和 EDGE** 的 GENERATED/MODIFIED 全部路由到 `_write_audit_relation`（纯 `TDataStd_AsciiString` JSON）；`test_feature_relation_audit.py` 有断言 | ✅ 已完成 |
| **P1-2** 身份键覆盖 | 3 处缺口 | `make_relation_key` 覆盖 boolean/revolve/fillet/chamfer/mirror/unify/offset_sweep/pattern；`make_source_ref` 覆盖 fillet/chamfer/mirror/unify/offset_sweep/pattern | ✅ 已完成 |
| **P1-3** edge role 覆盖 | 未覆盖 | 全算子产出 `edge_roles`；`test_op_record_coverage.py` 断言每个算子 `edges_covered == edges_total` 且 `history_complete=True` | ✅ 已完成 |
| **P1-4** merge / delete / split | merge 缺、delete 靠几何指纹 | delete 已改为**权威 TShape 比对**：`_read_shape_anchor()` 读 `SHAPE_ANCHOR` 的 original shape 做 `IsSame/IsPartner`，几何指纹退为无 anchor 时的 fallback。merge / split 跨 revision 测试齐备 | ✅ 已完成 |
| **P2-1** OCP 多版本矩阵 | 只有 7.8.1.1 | Python/OCP 侧 **3 个解释器**全绿（7.8.1.1 / 7.8.1.0 / 7.9.3.1）；**C++/OCCT 侧仍只有 1 个版本**（OCCT 7.8.1） | ⚠️ 部分完成 |
| **P2-2** 非 role 依赖闭包 | 回退 component terminal | `run.py:_resolve_feature_for_shape()` 逆序找真正生产/修改该 shape 的 feature，用 `_is_carry_through()` **排除纯透传**；仅解析失败才退 `_resolve_component_terminal_node()` | ✅ 已完成 |

### 3.4 真实残留缺口（仅两项）

1. **C++/OCCT 侧仍只有单版本**。加第二个版本需要联网 conda 环境。
2. **多组件 / 跨组件依赖闭包仍偏保守**。若 `missing_feature_ref`，整体退回 component scope。

### 3.5 两个待修问题

| 问题 | 说明 |
|---|---|
| **320 个测试不在 CI 里** | `.github/workflows/ci.yml` 跑根目录 `pytest -q`，而根 `pyproject.toml` 的 `testpaths = ["tests"]`——ocaf 这套完全没被覆盖。`scripts/check_xfail_policy.py` 也只扫根 `tests/`。目前「全绿」只靠人工跑。 |
| **死引用** | `topology/ocaf/__init__.py` 的 docstring 仍列着 `selectors.py — DEPRECATED`，但该文件已不存在。 |

---

## 4. Agent 自动仿真系统

状态：**代码齐全、各有一次真实成功，但未接线进主流水线，且 CFD 侧 LLM 未启用**。

### 4.1 CFD 链路（Fluent 18.1）

```
SimulationSpec → Orchestrator 状态机（preflight→topology→domain→mesh→physics→initialize→solver→postprocess→complete）
  → 每次算子调用 = 一次文件 RPC → fluent_worker.py 子进程（stdin/stdout JSON）
  → 内部再起 fluent.exe / fe.exe 子进程（TUI journal 批处理，非 API）
```

- 包：`integrations/cfd/src/seekflow_cfd/`，有独立 CLI `python -m seekflow_cfd {schema|validate|run|batch|summary}`
- 真实求解器 Worker **不在包里**，是外部受信脚本 `_cfd_experiment/local/fluent_worker.py`（约 1500 行）
- 七个算子：`domain.construct` / `mesh.generate` / `physics.configure` / `solver.initialize` / `solver.advance` / `solver.stop` / `results.extract`
- 网格：Gmsh OCC 布尔 + 四面体 → I-deas UNV → `fe2ram` 转 Fluent native `.msh`
- **进程模型**：Worker 每次调用退出后进程组被清理，不支持常驻 Fluent daemon，必须靠 case/data 文件重启

### 4.2 结构链路（ANSYS 18.1 APDL）

```
Agent 自主 list_features 发现轮缘槽 → 选真实 TopoDS 实体 → 选承力面
  → StructuralIntent（LLM 产出，物理值只能从显式 case 文件抄）
  → structural_apdl.render_apdl() → solve.inp
  → AnsysAPDLRunner（ansys181.exe -b -m <mem> -i solve.inp -o out -j jobname）
  → postprocess_structural.py → nodal_stress_3d.csv / metrics.json / report.md / .png
```

**刻意反模板**：不导入 `apdl_template_3d.py`、不读 golden face list、不使用确定性盘体模板（见 `_structural_experiment/README.md` 的 Anti-Template Boundary 章节）。缺叶片载荷时正确返回 `needs_input` 而不猜。

`_structural_experiment/` 是**一组 argparse 单文件脚本**，无统一 CLI、无 `__main__.py`、无 entry_points，靠 README 里的 PowerShell 命令逐条调用。

### 4.3 必须说清的两个限定

**(1) CFD 主链路的 LLM 未启用。**
D01/D05 的 `record.json` 里 `agent_trace` 长度为 **0**，即正式 run 时 `experts=None`，用的是**手写并人工确认的 spec**（`_cfd_experiment/dev/specs/d01_outer_fluent_steady_lowre.json` 等）。
LLM 专家评审确实跑过，但是**离线单独跑的**（`_cfd_experiment/output/dev/agent_reviews/d01-steady-lowre-1.json`，5 个专家 trace + `result_review: accept`）。框架具备，主链路未启用。

**(2) 自动调参循环存在但被极度收窄。**
只允许两个动作：`refine_mesh`（仅缩小 global/local size，仅 `stage=="mesh"` 生效）、`reduce_relaxation`（仅减小 relaxation，仅 `stage=="solver"` 生效）；否则 `give_up`。且 `allowed_repairs` **默认 `[]`**——默认不允许任何自动修复。

### 4.4 未接线

全仓 `seekflow_cfd` 的引用排除包自身后**只有 6 处，全是开发 / 实验脚本**：`fluent_worker.py`、`prepare_cfd_bundle.py`、`dev/review_spec_with_llm.py`、`dev/gmsh_mesh_variant.py`、`dev/promote_roles_probe.py`、`.github/workflows/cfd.yml`。

`app/` 和主 pipeline **零调用**。`service.py` 的注释自己写着 "CAD calls this service explicitly after generation"——**设计要求接线，但仓库里没有装配代码**。

`_structural_experiment/` 同样无装配。这是「agent 自动仿真」真正成立的前提。

### 4.5 真实产物与最近运行状态

**D01 CFD（成功）** — `_cfd_experiment/output/dev/jobs/d01-steady-lowre-1/`
`status: success`，`is_mock: false`，240 次迭代，收敛窗口 `[238,239,240]`，质量相对误差 `1.7e-8`，7 个门全 pass，耗时 502.4 s。网格 96,210 四面体，最小正交质量 0.0683。产物含 25 组 checkpoint（约 170 MB）。报告：`docs/自动CFD-D01真实全链路验证报告.md`。

**D19 结构（成功）** — `_structural_experiment/work/D19_structural_smoke/`
28,239 节点 / 4,588 有应力结果节点；最大位移 2.5388 mm；最大 von Mises 1151.076 MPa；选面最大 142.055 MPa；合力相对误差 1.13e-14；最小屈服安全系数 0.869。完整 ANSYS 产物（`.rst` 18.9 MB / `.full` 43 MB / `.db` 30 MB）。报告：`docs/自动结构仿真-D19验证报告.md`。

**⚠️ 载荷为显式合成的 10 kN/槽，非确认工程结论**，结果状态 `synthetic_or_unconfirmed_pipeline_validation`。

**D19 选面 → Fluent 边界** — `docs/自动CFD-D19选面到边界验证报告.md`
3,910 个面中 Agent 自主选出 8 个工作齿面 `17,25,33,41,53,61,69,77`，唯一映射到 8 个独立 Fluent boundary，剩余 3,902 归 `remaining_disc_wall`，未覆盖 0。proof = `exact_brep_transfer`。**注意：只验证了边界传递接口，没有做 D19 的 CFD 求解。**

**D19 跨 revision 复验（亮眼）**
rev-000002 把榫槽 cutter 截面宽度扰动 2%，同一个 Agent 选出的 8/8 role ID 原生复解成功：面积相对变化 0.795%–1.648%，最大质心移动 0.130 mm，法向绝对点积 ≥ 0.99995。**这条把拓扑命名与仿真两条线扣上了。**

**近零载荷对照**：新中性管线最大 von Mises 1124.595 MPa vs 旧非 Agent 基线 1123.468 MPa，相对差 0.1003%——证明相同转速/温度/材料/约束下新实现无求解退化。

**D27 结构（2026-09-11 重做，此前全部结论作废）**

旧结论建立在两个缺陷上，均已修复，修复前的 D27 数字不可再引用：

1. **几何被静默截断**：配置 `z_half_mm = 38` 小于零件实际半厚 **42.207**，轮缘被削掉 4.2 mm，且不报错。
2. **分析域是错的**：配置写死 `sector_deg = 6.0`，但 D27 是 60 槽 + 20 孔，`gcd(60,20)=20`，真实重复单元是 **18°（阶 20）**。3–9° 那个楔形里**根本没有孔**。

重做后由 agent 自主判定并求解（`_structural_experiment/work/D27_mesh_agent_18/`）：
18° 扇区（θ_low = 9°，z 对称），314,441 节点 / 185,208 单元，minSICN 0.0477，非正雅可比 0，最大位移 3.223 mm。

**载荷施加方式已于 2026-09-12 更换**，由逐节点集中力改为 `SFE` 均匀面压力。同网格同温度同材料同约束的三组对照（`_structural_experiment/work/D27_abc/`）：

| 指标 | A 节点力（旧） | B SFE（现） | C 故意错 LKEY（正对照） |
|---|---|---|---|
| 最大位移 mm | 3.22314 | **3.22315** | 3.25317 |
| 最大 von Mises MPa | 1553.78 | **1482.90** | **6775.03** |
| 峰值位置 r mm | **212.29**（载荷面） | **60**（内孔） | 60 |
| 载荷面峰值 MPa | 1553.78 | 1392.86 | 1333.93 |
| 最小安全系数 | 0.623172 | **0.674354** | 0.147601 |

**结论**：`SFE` 使全局峰值**从载荷面迁回内孔**——旧的 1553.78 MPa 是载荷施加伪影，物理上的控制点是内孔。A 与 B 位移吻合到 3e-6 相对（合力相同），C 给出 4.6 倍应力，证明这组指标对错误的 `LKEY` 敏感、A-vs-B 的吻合因此有意义。

**可引用的 D27 结论**：内孔峰值 **1482.90 MPa，最小安全系数 0.6744**，最大位移 3.2232 mm。

**载荷面峰值不可引用**。判定依据不是"数字大"，而是：旧的节点力路径在同一网格上**不通过常应力分片试验**（精确解 σ_xx=−p，实测误差达 183%，并产生 5.8 MPa 的虚假 σ_yy），而 `SFE` 路径到求解器精度通过。

**注意**：位移对叶片载荷几乎不敏感（A/B/C 三组都在 3.22–3.25），**不可**用作加载方式的回归判据；应力类指标才行。

**未做**：`SFE` 路径的收敛检验尚未跑（上表是单级网格）。载荷仍为显式合成的 10 kN/槽，状态 `synthetic_or_unconfirmed_pipeline_validation`。

### 4.6 最近一次运行时间线（2026-09-10）

| 时间 | 事件 |
|---|---|
| 03:33–03:45 | `d01-real-full-1/2/3` 均 **failed**（Z 向来流，残差停在 3e-2） |
| 12:24–12:31 | **`d01-steady-lowre-1` success**，240 迭代 |
| 12:38–12:39 | LLM 专家评审（离线） |
| **12:42–12:43** | **`d05-steady-lowre-1` failed**，`stage=mesh`，`min_orthogonal_quality = 0.0012 < 0.05` ← CFD 最近一次运行 |
| **13:45–14:07** | **结构 D19 ANSYS 求解成功** ← 结构最近一次求解器运行 |
| 14:07–21:34 | 选面 / 角色索引 / 跨 revision 验证，**未再跑求解器** |

### 4.7 选面 agent 的实测行为（2026-09-12）

**方法**：把选面 agent 单独拎出来跑（`_structural_experiment/probes/sweep_one.py`），同一份输入并行 N 次，每次记录**完整对话、每条工具回复、每步 rationale、每段沙箱代码与输出**。记录在 `_structural_experiment/output/sweep*/run_*.json`，分析器 `probes/analyse_sweep.py`。

**为什么要这么测**：此前三次对它的判断都是从**单条轨迹**推的，三次全错。单条轨迹说明"发生过一次"，说明不了"这是它的行为"。本机 20 逻辑核 / 31.8 GB，每次运行约 1 GB，实测 12 路并行稳定。

| 批次 | n | 提交 | **正确** | 选错 | 未提交 |
|---|---|---|---|---|---|
| 基线（旧列表） | 23 | 9 | **9（39%）** | 0 | 14 |
| +分布直方图（已撤） | 24 | 16 | 7（29%） | **9** | 8 |
| +仅紧凑列表 | 24 | 19 | **14（58%）** | 5 | 5 |
| 最新（列表 + 沙箱文档） | 10 | 7 | 4（40%） | 3 | 3 |

**n=10 与 n=24 区分不开**（区间 17–69% vs 39–76%）。当前代码合计 34 次：**正确 18（53%）、选错 8、未提交 8**。

#### 三类错误，性质完全不同

**① 选错类别 —— 8 次里 7 次选中同一批面（模型内无解）**

```
选错的： 下标 9..24   θ 16.40–19.60   r 202.23–213.77   来源 carry/target
正确的： 下标 3954..  θ 16.67–19.33   r 280.73–295.39   来源 modified/tool
```

**同一个槽、同一个方位角，只差半径 70 mm。** 两者**都是榫齿状锯齿**，都由平面组成，都是镜像成对，法向都是朝内。

agent 的推理是连贯的——有运行明确写下 *"in the low-radius groove band"*。**它知道自己在选低半径那一条，并认为那才是承力面。** 有运行把两条带都选了（32 个面，r 209→295）：**它在两个同样合理的答案之间没有依据。**

`check_criterion` 全部通过，因为**判据是 agent 自己写的**——通过只证明自洽。

**② 重复循环 —— 8 次未提交里占 5 次**

三种形态都出现过：纯 `query_faces` 循环（最长 23 次）、沙箱脚本循环（7 次，代码逐字节相同）、两者混着（12 次）。

**触发点**：三个来源类依次看完（第 5–7 次调用），**不选任何一个**，然后开始重复。成功的那条路径同样是先浏览三个类，**区别是第 8 次会定下一个类并开始加过滤**（扇区 → 法向 → 类型），循环的那些停在原地。

**尝试过并已被证伪的干预**：工具回复里加"这是第 N 次相同调用，答案不会变"——实测发了 21 次被完全无视。**这个模型对工具回复里的建议性提示不行动。**

**③ 探索到耗尽 —— 3 次**：在做实质分析（枚举、对比），30 次调用不够。其中一次最后 6 次全在纠结"18° 扇区里有 3 个槽是不是理解错了"——**范围文字 "one sector's worth" 在"1 个槽"和"整个扇区（3 个槽）"之间有歧义。**

#### 本轮已修复

| | 证据 |
|---|---|
| **溯源索引** | 3 小时 → **29.7 秒**（≈360×）；只解析面级角色、carry 走形状匹配（崩溃源消失）、大批量；前驱从文档识别不写死名字 |
| **溯源工具** | `list_origins`（含扇区内计数）+ `origin_relation`/`origin_operand` 过滤器 |
| **代码沙箱** | `run_analysis` + `sandbox_kit`；子进程需要 `SystemRoot`/`TEMP` 否则几何栈以 `WinError 10106` 失败 |
| **紧凑列表** | 按**回复字节**限界；195 个面 10 KB 全列（旧 `describe` 要 43 KB，而且**以前一个都不给**）→ 重复循环从 9/24 降到 1/24 |
| **扇区限定** | 选面 agent 现在知道只有 9°–27° 会被网格化 |
| **载荷方向检查** | `load_pushes_outward`：正确答案 +0.742，盘外圆柱面 −1.000，孔壁 ≈0 |
| 12 处真 bug | `theta_deg` 恒为 0（对称校验从未工作）、`area/area_mm2` 键名、`z_symmetry` 误判、`convergence_check` 依赖从不存在的 intent 文件、账本漏记、声明了却从不求值的子句…… |

**被撤掉的一项**：`summarise` 里的分布直方图。24 次对照实测：提交率 39%→67%，但**错答案从 0 个变成 9 个**（p≈0.002）。它让 agent 更果断而不更知情，而链路把 9 个全接受了。

#### 未解决，以及为什么

**① 和 ③ 都无法用工具解决。** 选面 agent 的工具已经够用（三个来源类、扇区、法向、类型、自查判据），而"看过三个类之后要选一个继续收窄"是决策行为。加"请选定一个类"的规则，和那五种被无视的提示是同一类东西。

**② 从根本上需要模型里没有的信息。** 两条榫齿带在所有几何量上无法区分，而"叶片实际压在哪一条上"取决于叶根几何或工程判断——**D27 模型里没有叶根**。

**方向检查只堵住四类错答案中的一类**：它看的是"压力往哪推"，不是"往哪里推"——位置错的承力侧面和位置对的得分几乎一样（0.652 对 0.742）。这个限制已写进 `checks.load_pushes_outward` 的 docstring 并加了测试钉住。

**唯一能真正改变这条路径的**：把"载荷从轮缘那一族进入"作为工程判断写进参数文件（与 `direction_rule` 同性质），或者提供叶根几何。

---

## 5. 三线接缝与文档一致性

### 5.1 接缝设计（已就绪）

见 §1.3。`RawSelectionSpec` + `RawCaeBinding` 是 LLM 声明拓扑选择 → OCAF 持久命名 → CAE 语义绑定的唯一通道。

### 5.2 接缝未装配

见 §4.4。

### 5.3 文档一致性

仓库里存在**主动误导**的文档，接手前必须知道：

| 文档 | 状态 |
|---|---|
| `PERSISTENT_TOPOLOGY_NAMING_GAPS.md` | **已删除**（2026-09-10）。原内容把 P1-1/P1-2/P1-3 全列为待办，而这三项在 `96a7db2` 那一批就已闭环。 |
| `PERSISTENT_TOPOLOGY_NAMING_STATUS.md` | **已改为短跳转页**（2026-09-10）。原内容的 P1-4 / P2-1 / P2-2 判断均已被后续提交推翻；测试数字 `289 passed, 4 skipped, 1 failed` 与实测 `320 passed` 不符；§7 的「推送受阻」陈述已无意义（本地 main 已领先到 `606ab55`）。 |
| `GENERATION_INTEGRITY_AUDIT.md` | **有效**，内容准确。 |
| `_main_experiment/EXPERIMENT_VALIDITY.md` | **有效**，是必须向审稿人披露的边界清单。 |
| `_main_experiment/output/DATA_INTEGRITY.md` | **有效**，实验数据缺失项清单。 |
| `integrations/cfd/README.md` | **有效**，但写作时基线是 `606ab55`，注意其自陈的未验证项。 |

### 5.4 测试数字对不上

| 来源 | 声称 |
|---|---|
| `PERSISTENT_TOPOLOGY_NAMING_STATUS.md` | `289 passed, 4 skipped, 1 failed` |
| `PERSISTENT_TOPOLOGY_NAMING_GAPS.md` | `291 passed, 1 deselected` |
| **实测（2026-09-10）** | **`320 passed, 0 failed, 0 skipped, 0 deselected`** |

旧文档提到的 flaky 用例 `test_abort_then_retry_succeeds` 本次也 PASSED。

这两份文档已于 2026-09-10 处置完毕：`GAPS` 删除，`STATUS` 改为跳转页。上表保留为处置依据的历史记录。

---

## 6. 版本控制状态

### 6.1 未提交改动（5 个文件，+281 / −105）

主题是 `tracked_circular_pattern` 正确性与性能：

| 文件 | 改动 |
|---|---|
| `topology/ocaf/label_index.py` | `allocate_relation` / `allocate_face_role` / `allocate_edge_role` 的 tag 分配加 `while` 循环跳过已占用的 TagPath（修 Tag 冲突） |
| `topology/ocaf/tracked_ops/_carry.py` | 新增 `ShapeIndex`（`TopTools_IndexedMapOfShape`），把 `all_faces_accounted` / `carry_unchanged_faces` 从 O(N²) partner 扫描降为 O(1) |
| `topology/ocaf/tracked_ops/boolean.py` | 改用 `ShapeIndex` 做结果面/边精确查找；删除 `_find_partner_face` |
| `topology/ocaf/tracked_ops/pattern.py` | 重写（+105 / −72）：单次多 tool fuse，实例重叠时回退顺序 fuse |
| `tests/.../test_geometry_ab.py` | 新增 `TestCircularPatternAB`（单次 fuse 对齐原生 union、重叠实例回退顺序 union） |

**§3.2 的 320 passed 是带这些改动跑出来的。**

### 6.2 未纳入版本控制（untracked）

```
integrations/cfd/                      # 整套 CFD 框架
_cfd_experiment/                       # CFD 实验与 Worker
_structural_experiment/                # 整套结构仿真
.github/workflows/cfd.yml
docs/issues/cfd-input-generation-performance.md
docs/issues/cfd-real-mesh-quality-gate.md
docs/自动CFD仿真-架构与实施设计.md
docs/自动CFD仿真-Agent需求文档.md
docs/自动CFD-D01真实全链路验证报告.md
docs/自动CFD-D19选面到边界验证报告.md
docs/自动结构仿真-Agent实施方案.md
docs/自动结构仿真-D19验证报告.md
```

**今天（09-10）一整天的仿真成果只存在于工作区一个副本里。**

### 6.3 无关目录澄清

| 目录 | 实际用途 |
|---|---|
| `_p8_envs/` | OCP / pythonocc 的两个虚拟环境（`ocp-7.8.1.0`、`ocp-7.9.3.1.1`），服务于拓扑命名。**与仿真无关。** |
| `tools/` | `ocaf_status_manifest.py`、`topology_stress_test*.py`，OCAF 拓扑压力测试。**与仿真无关。** |
| `output/` | `chaos/`、`complex_agents/`、`mcp_server/`、`production_agents/`、`v3_production_tests/` 均属 CAD 生成侧实验。 |
| `../auto_detection_process_main_experiment/` | **空壳**。2 个 0 字节文件，2026-09-10 23:14 新建。全仓唯一的 `AERODISK_PLACEHOLDER_*` 生成器 `_paper_metrics_v4pro_placeholder.py` 硬编码输出到主项目的 `_main_experiment/output/`，**不会写入这里**。与当前代码库无生成关系。 |

---

## 7. 实验与数据状态

### 7.1 数据量

| 实验 | 记录数 | 成功 |
|---|---|---|
| 主实验 full_agentic | 400 | 261 |
| 消融 direct_base | 120 | 68 |
| 消融 single_agent / multi_no_repair / multi_inner / full | 各 120 | 41 / 0 / 101 / 103 |
| GLM5.2 | 400 | 243 |
| Qwen3.7 | 400 | 108 |
| DeepSeek v4-flash | 400 | 167 |
| 参数扰动再生 | 800 | 724 |
| 语义等价（agentic） | 320 | — |
| 不可行设计 | 240 | 240 拒绝 |
| 工程验证工具 | 2400 | — |

### 7.2 已披露的缺失项

1. **GLM5.2 的 T37 seed6/7/9（3 个成功 run）缺 `metrics.json`**——golden T37 参考 STEP 导入超过 300 s 超时，几何指标无法计算。核心原始数据齐全。
2. **Qwen3.7 的 39 个 run 缺 `usage`（token）记录**——采集时未写入，无法恢复。
3. 消融 direct_base 的 52 个失败 run 无 `metrics.json`（正常，失败无指标）。
4. 若干 failed run 无 `repair_summary.json`（未进入修复循环，符合流程）。

### 7.3 必须披露的实验边界（摘自 `EXPERIMENT_VALIDITY.md`）

1. **模型口径**：当前结果是「当前 agentic harness + DeepSeek-v4-pro」，**不是论文的 AeroDisk-LLM（QLoRA 微调）**。
2. **参考 golden 由参数化模板自动生成**，不是独立专家建模。本基准衡量「agent 与模板一致性」，与论文「专家确认参考」不同。
3. 8 个编辑任务是**文本式编辑**（prompt 写「保持原有主体结构」），未向 agent 注入既有模型实体。
4. 关键尺寸 / 孔 / 槽参数测量来自修复后 IR；体积 / 表面积来自最终 STEP；**bore 内径、槽深等未做独立截面测量**。
5. seed 已传给 API；DeepSeek 服务端是否严格保证 seed 确定性需实测，复现性取决于服务端。
6. 榫槽 worker 存在 LLM 级波动，按真实结果记录。
7. 商业 CAD 导入、专家一致性、训练类实验不在本环境，不混入主实验。
8. **T24（D28 耦合变体）**曾因孔外缘切入轮缘内壁产生 0.0085 mm 数值细缝，已调 PCD 210 → 205。**调整前采集的 10 次运行无效，需重跑。**

### 7.4 已知可靠性边界

- **T16（D14 锥形环槽）**：根因是基准 prompt 缺「锥形腹板」信息 + legacy autofix `fix_slot_half_profile` 误把 `groove_cutter` 当榫槽半剖面镜像合并轮廓。两处均已修复，真实运行 2/2 通过。
- **T21（large_hub 槽盘）**：剩余边界为 Agent B 榫槽 worker 的 LLM 可靠性——偶发自写近似算法或直接留下占位点，且 repair 层无法归因（0 candidate nodes / 补丁重复）。已修正 prompt 中「参数即坐标」的自相矛盾表述，但**仍按真实结果记录，不做掩盖性修复**。

### 7.5 论文—代码一致性缺口

`docs/论文代码一致性审计.md` 记录论文与代码的逐条对照，标出三大缺口：**AeroDisk-LLM / SER / NL2DiskCAD**。全库 `grep AeroDisk` = **0** 条。

这是当前最大的实质风险，需要在论文中显式处理。

---

## 8. 风险清单

按优先级排序：

| # | 风险 | 严重度 | 说明 |
|---|---|---|---|
| 1 | **论文口径差** | 🔴 高 | 论文声称 AeroDisk-LLM / SER / NL2DiskCAD，代码零实现。已在 `EXPERIMENT_VALIDITY.md` 披露，但需论文层面对齐。 |
| 2 | **大批成果未提交** | 🔴 高 | 09-10 全部仿真成果 + 5 个 OCAF 改动只存在于工作区单一副本。 |
| 3 | **两份交接文档主动误导** | 🟠 中高 | 会直接误导下一个 agent 重复已完成的工作。 |
| 4 | **320 个 ocaf 测试不在 CI** | 🟠 中 | 最成熟的模块没有回归保护，全绿只靠人工跑。 |
| 5 | **双链路代码重复** | 🟠 中 | 生产链路与实验链路需手工同步，易漂移。 |
| 6 | **CFD D05 卡网格质量门** | 🟠 中 | `min_orthogonal_quality = 0.0012 < 0.05`。D01 早期同一问题已通过 Gmsh 距离场 + Fluent `improve-quality` 解决到 0.0683。 |
| 7 | **CFD 拓扑束生成过慢** | 🟠 中 | D19–D32 单族 32–90 分钟，根因是槽/孔阵列实时拓扑捕获超线性。**D20/21/22/28/30/31/32 未完整生成。** |
| 8 | **仿真未接线** | 🟡 低（但阻塞目标） | 设计已就绪，缺装配代码。 |
| 9 | **C++/OCCT 单版本** | 🟡 低 | 需联网 conda 环境。 |
| 10 | **docstring 死引用** | ⚪ 极低 | `ocaf/__init__.py` 引用已不存在的 `selectors.py`。 |

---

## 9. 建议下一步

按投入产出比 × 阻塞程度排序：

1. **把 320 个 ocaf 测试加进 CI**
   改 `.github/workflows/ci.yml` 加一条 ocaf 目录的 pytest，并把 `scripts/check_xfail_policy.py` 的扫描范围扩到该目录。半小时的事，但当前最成熟的模块完全没有回归保护。

2. **提交在途改动 + 追踪仿真目录**
   5 个 OCAF 文件 + `integrations/cfd/`、`_cfd_experiment/`、`_structural_experiment/`、7 篇 docs。先确认 `.gitignore` 不会把大体积产物（D01 的 170 MB checkpoints、D19 的 43 MB `.full`）一起提交。

3. **接线 `seekflow_cfd` 到主 pipeline**
   实现 `service.py` 注释里承诺的「CAD calls this service explicitly after generation」。这是「agent 自动仿真」真正成立的前提，也是 `RawSelectionSpec` / `RawCaeBinding` 接缝的兑现。

4. **解决 D05 网格质量问题**
   复用 D01 的解法（Gmsh 距离场 + Fluent `improve-quality`），然后跑 D19 的真实 CFD 求解——目前只验证了选面到边界的传递接口。

5. **恢复 CFD 的 LLM 专家链**
   在正式 run 中启用 `experts=ExpertTeam(...)`，让 `agent_trace` 不再为空。这是「agent 自动仿真」名副其实的关键一步。

> 原第 3 项「处置两份作废文档」已于 2026-09-10 完成（`GAPS` 删除，`STATUS` 改为跳转页），故不再列出。

---

## 10. 复现命令

```bash
# 环境（必须用项目虚拟环境，系统 Python 3.13 缺 cadquery / OCP）
cd e:/text_to_cad_improve/auto_detection_process

# 拓扑命名全量测试（约 5 分钟）
.conda/python.exe -m pytest integrations/engineering_tools/tests/generative_cad/topology/ocaf/ -v

# C++ 原生 fixture
.conda/python.exe integrations/engineering_tools/tests/generative_cad/topology/ocaf/cpp_fixture/run_fixture.py

# OCP 多版本矩阵
.conda/python.exe integrations/engineering_tools/tests/generative_cad/topology/ocaf/cpp_fixture/run_ocp_matrix.py

# CFD（Mock，不需要许可证）
python -m pip install -e 'integrations/cfd[dev]'
python -m seekflow_cfd run integrations/cfd/examples/mock_spec.json --backend mock --job-id demo
python -m pytest integrations/cfd/tests -q

# 结构仿真
.conda/python.exe -m pytest _structural_experiment/tests -q

# 主实验
python -m _main_experiment.cli golden
python -m _main_experiment.cli aggregate
python -m _main_experiment.cli report
```

---

## 附录 A：关键路径速查

### CAD 引擎

```
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/
  ir/raw.py                    RawGcadDocument —— LLM 唯一允许输出的格式
  ir/canonical.py              CanonicalGcadDocument —— 校验/解析/带 hash
  ir/raw.py:112-137            RawSelectionSpec / RawCaeBinding —— 通往仿真的接缝
  pipeline/run.py              引擎入口 run_gcad_core / run_canonical_gcad
  validation/pipeline.py       validate_and_canonicalize_with_bundle
  validation_kernel/stages.py  ValidationStage 单一事实来源
  repair_kernel/orchestrator.py:run_generation_loop   修复总编排
  repair_kernel/config.py      RepairLoopConfig —— 全部预算
  authoring/auto_fixer.py      确定性修复链，约 40 个 _fix_*
  skills/orchestrator.py       L1/L2 prompt 与 tool 构建
  llm/deepseek_client.py       DeepSeekToolCaller.call_strict_tool
```

### 拓扑命名

```
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf/
  models.py            SourceEntityRef / RelationKey / FaceRoleSpec / EdgeRoleSpec
  schema.py            Tag100 固定树，ROLE_TAG_BASE=1001
  writer.py            TopologyNamingWriter.write_batch
  label_index.py       StableLabelIndex —— key → TagPath 稳定映射
  selection_service.py PersistentSelectionService.create / solve
  document.py          OcafDocumentSession
  cae_preflight.py     run_cae_preflight —— proof gate
  verify_worker.py     子进程 XBF 校验（崩溃隔离）
  tracked_ops/         11 个文件
```

### 生产与实验

```
app/text-to-cad/server/main.py         FastAPI + _run_pipeline 主编排
app/text-to-cad/server/agentic_l2.py   Agent A/B 双阶段（116 KB，核心）
_main_experiment/pipeline.py           run_experiment_task
_main_experiment/EXPERIMENT_VALIDITY.md 必须披露的实验边界
_param_experiment/design_families.py   32 族 D01–D32 定义
_param_experiment/param_templates.py   确定性参数化模板
_param_experiment/mcp_tools.py         MCP 质量门（15 工具，生产用 6 项子集）
```

### 仿真

```
integrations/cfd/src/seekflow_cfd/
  agents.py        ExpertTeam —— 5 类专家，prompt 内联
  orchestrator.py  状态机 + 预算 + 修复闭环
  evidence.py      DomainReport / MeshReport / SolverReport / ResultReport
  topology.py      OCAFTopology / IsolatedOCAFTopology
_cfd_experiment/local/fluent_worker.py        真实 Fluent Worker（约 1500 行）
_structural_experiment/agent_solid_face_intent.py   Agent 选实体 + 选承力面
_structural_experiment/agent_structural_intent.py   Agent 生成 StructuralIntent
_structural_experiment/structural_apdl.py           中性 APDL 物化器
```
