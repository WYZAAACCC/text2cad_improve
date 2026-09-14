# SeekFlow CFD Agent

基于 `WYZAAACCC/text2cad_improve` main 的 `606ab553cea1a9697333c63524396d15867d84e5` 实现。
这是独立、可运行的 CFD Agent **控制与验证框架**。Mock 流水线不需要 CAD、LLM 或求解器许可；真实 Ansys 域/网格/求解操作由本地可信 Worker 实现。

## 安装与 30 秒验证

在仓库根目录使用项目虚拟环境：

```bash
python -m pip install -e 'integrations/cfd[dev]'
python -m seekflow_cfd validate integrations/cfd/examples/mock_spec.json
python -m seekflow_cfd run integrations/cfd/examples/mock_spec.json --backend mock --job-id demo
python -m seekflow_cfd summary
python -m pytest integrations/cfd/tests -q
```

Mock 样例已经设置 `expert_confirmed=true`，仅为测试夹具，不代表该水流算例得到物理专家确认。
不要把该 JSON 的几何哈希占位符或确认标志直接用于真实算例。

输出默认位于 `_cfd_experiment/output/jobs/demo/`：

| 文件 | 用途 |
| --- | --- |
| original_spec.json | 原始 Spec；重放/恢复的身份依据 |
| simulation_spec.json | 本轮最终 Spec；修复产生新哈希 |
| topology_face_map.json | 选择解析、原生证明、当前 revision 面句柄 |
| native-faces/*.brep | 真实 OCAF Worker 导出的实际命名面 |
| domain_report.json / mesh_report.json | 计算域覆盖、边界传递和网格质量证据 |
| calls/*.json | 每次通用算子的完整输入与输出 |
| events.jsonl | 包含哈希链的调用与修复日志 |
| state.json | 原子状态检查点；含累计迭代/时间/调用消耗 |
| record.json | `cfd_sim_v1` 记录及结构化失败诊断 |
| residuals.csv / residuals.svg | 残差数据和无额外绘图库依赖的图形 |
| report.md / results.json | 人类可读报告与结果 |
| manifest.json | 文件 SHA-256 完整性清单 |
| attempts/ | 各次失败与修复前的证据 |

Mock 输出显式携带 `is_mock=true`，网格是合成元数据，不能用于物理解读。
批量汇总将真实和 Mock 成功率分开，只有真实成功记录可参加网格无关性比较。

## 模块与职责

| 模块 | 职责 |
| --- | --- |
| models.py | Pydantic Spec、SI 参数、跨字段约束、规范序列化和哈希 |
| agents.py | Orchestrator + 五类专家；结构化规划、评审、结果复核与修复提案 |
| topology.py / topology_worker.py | OCAF 原生解析、跨 revision 比较、实际命名面导出、历史证明侧车 |
| tools.py | 通用算子注册、调用者角色约束、输出 schema 校验 |
| evidence.py | 域/网格门、守恒/残差/监测量窗口、量纲与合理性验证 |
| orchestrator.py | 状态机、预算、审计、失败闭环、恢复与重放 |
| backends.py | Backend/Capabilities 协议和确定性 Mock |
| local.py / process.py | 固定命令文件 RPC、超时、进程组与资源边界 |
| service.py / api.py | 有界本地任务队列、MCP 注册与可选 FastAPI 接口 |
| reporting.py / cli.py | 报告、批量统计、命令行入口 |

无需修改 `agentic_l2.py`、CAD 原语、现有 OCAF 实现或原有工程工具注册表。

## 自然语言规划与原有 LLM 协议接入

`ExpertTeam` 直接兼容 CAD 已使用的 `caller.call_strict_tool(...)` 协议：

```python
from seekflow_cfd import ExpertTeam
from seekflow_engineering_tools.generative_cad.llm.deepseek_client import (
    DeepSeekToolCaller,
)
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig

team = ExpertTeam(
    DeepSeekToolCaller(),
    LlmModelConfig(model="<your-configured-model>"),
    max_calls=10,
    timeout_s=60,
)
proposal = team.plan(
    text="分析冷却通道的流动，输出出口平均压力",
    geometry=geometry_ref,  # GeometryRef，由实际生成结果构建
    topology_roles=topology.list_topology_roles(),
    explicit_parameters={
        "physics_spec": {"reference_pressure_pa": 101325},
        "solver_control": {"max_iterations": 1000},
    },
)
```

以上是接入片段：`geometry_ref` 与 `topology` 必须由已验证 CAD 结果提供。

- `needs_input` 返回具体缺失问题，不编造入口、工质、温度、转速等硬参数。
- `explicit_parameters` 是 Spec 的嵌套部分对象；代码逐项验证 Agent 没有改值。
- Agent 不能自我确认：规划出口强制 `expert_confirmed=false`。
- 确认完整 Spec 后，显式交给 `CFDOrchestrator(..., experts=team)`；五类专家评审不能绕过确定性质量门。
- 结果提取后，Verification Agent 再次审查真实证据；可疑结果保留 `requires_manual_review`。
- 默认不调用 LLM；Mock CLI 与手写已确认 Spec 均可完全离线运行。
- 未实测真实模型 API。现有 `DeepSeekToolCaller` 的 `timeout_s` 会受框架配置约束；自定义 caller 必须实施传输超时和重试上限。框架的响应超时检查不能强杀任意 Python caller。

## 几何与拓扑身份

`GeometryRef` 必须指定输入根下的相对路径，并分别绑定 STEP/BRep、XBF、历史证明 JSON 的 SHA-256；同时包含 lineage、revision、CAD record_id 和长度单位。
CAD 默认 mm，网格和物理 Spec 一律 SI。**本地导入器必须实际完成 mm → m 转换**，不能只修改文件标签。

真实接口：

```python
from seekflow_cfd.topology import (
    OCAFTopology,
    IsolatedOCAFTopology,
    check_role_binding_stable,
)
```

`OCAFTopology` 适用于已隔离的可信工作进程；`IsolatedOCAFTopology` 是默认 CLI 的生产入口，在独立进程中批量解析并导出命名面。
`IsolatedOCAFTopology.prepare(...)` 完成后才能查询 roles 和 bindings；规划前也可用空 surfaces 批次只读取角色目录。

- 直接复用 `OcafDocumentSession`、`PersistentSelectionService.solve`、`collect_tnaming_labels`。
- 只接受 `unique/set`、`exact_kernel_history/exact_construction`、FACE、完整历史。
- 明确拒绝 `largest_area` 等 split_strategy，即使原服务将其标为 UNIQUE。
- `entity_ids` 是当前 revision / Worker 会话的面句柄，不宣称它们跨 revision 稳定。跨 revision 身份是 **lineage + selection_id + 原生重新求解**。
- 多边界一次批量解析，通过实际 `TopoDS_Shape.IsSame` 发现重叠；不按距离/面积配面。
- 新切割面必须返回构造证明；改变的原面必须返回 `parent_entity_ids`，并完整覆盖原选择。
- 网格必须原样携带域的 boundary_map，并为每个 BC 提供独立 solver zone label。
- 实际切割/导入过程中命名面的 BRep 与主域同一性的传递由本地域适配器实现。不能凭证据 JSON 的自我声明代替原生布尔历史；适配器属于需要测试、受信任的执行层。

`history_evidence` 的必要字段：

```json
{
  "lineage_id": "design-A",
  "revision_id": "rev-000001",
  "geometry_hash": "<实际 STEP SHA-256>",
  "topology_hash": "<实际 XBF SHA-256>",
  "history_complete": true
}
```

现有 pipeline 在内存 `TopologyCaptureSession` 中持有完整历史标志，并不保证旧产物已经包含上述 CFD 侧车。
`publish_history_evidence(...)` 可将**非空、完整、通过校验的 live capture**投影为侧车；在独立后生成接入层调用即可。
没有历史证据的旧模型必须重新捕获或补充可审核的原生证明，不能自动写一个 true。

## 本地 Ansys 接入

1. 复制 `examples/ansys_worker.py` 到本地受控代码目录。
2. 将经过本地验证的处理函数放入 `IMPLEMENTATIONS`。
3. 使用固定的绝对命令，例如 `[python_exe, worker_file]`；Agent 的 Spec 中不存在脚本/命令入口。
4. 根据实际支持能力配置 `Capabilities`；未实现能力不得宣称支持。
5. 先跑合同测试与一个人工确认的真实算例，再开启批量任务。

注意：现有 APDL runner 是 Mechanical/结构 FEA 路径。对 Fluent CFD，优先在本地实现 PyFluent 或 Fluent journal/TUI；CFX 可实现独立 CFX Worker。APDL 不应被当作通用 Fluent 接口。

本地 Fluent 18.1 Worker 现在支持两类外部边界：

- `generated`：外域六个侧面和未显式选择的 `solid_wall`；
- `selection`：由拓扑 Worker 导出的真实命名 BRep 面，通过面积、质心和
  零最短距离的唯一匹配转移到流体边界。

选面转移要求唯一性。匹配为零个或多个候选时返回结构化失败，不允许最近面
回退。转移谱系标记为 `exact_brep_transfer`；它不是 OCAF 原生 history 传递。
D19 最终盘体的 8 个 Agent 选面已全部唯一映射到 8 个独立 Fluent boundary，
剩余 3902 个面归入 `remaining_disc_wall`，未覆盖面为 0。

| Worker operation | 输入中的主要附加字段 | 必须返回 |
| --- | --- | --- |
| domain.construct | topology | DomainReport：体积、域、完整外边界库存、命名传递历史 |
| mesh.generate | domain、topology | MeshReport：真实质量指标、周期节点误差、BC zone map、网格文件 |
| physics.configure | domain、mesh | `{ok:true,spec_hash:...}`；实际材料/模型/BC 设置持久化到 job |
| solver.initialize | mesh | 同上；初始化 case/checkpoint |
| solver.advance | mesh、start_iteration、iterations、checkpoint | SolverReport：原始 Sample 序列、checkpoint、日志文件 |
| solver.stop | checkpoint | 同上；保存状态、释放进程/许可 |
| results.extract | mesh、checkpoint | ResultReport：请求对应的数值、单位、边界、导出文件 |

每次调用均传完整 `spec`；请求还含 protocol、call_id、input_hash，响应必须逐项回显。
返回 schema 在 `evidence.py` 和 `ToolRegistry.describe()` 中；可直接导出 JSON Schema 给本地实现者。
Worker 未实现方法时返回结构化 `capability_gap`，不会静默切换 Mock。

所有 Worker 文件必须在 job 内，日志/网格/checkpoint 文件必须存在。Worker 的**每个调用退出后**进程组都被清理，因此必须写 case/data 并支持下一次从文件重启；不支持默认常驻 Fluent daemon。
若需长驻求解器或远程 HPC，另写实现相同 Backend 协议的适配器，并提供其取消、预算和恢复保证。

### 运行与操作系统约束

```bash
python -m seekflow_cfd run confirmed_spec.json \
  --backend local --worker-config local_worker_config.json \
  --input-root /absolute/cad-output --output /absolute/cfd-output
```

`local_worker_config.json` 示例：

```json
{
  "command": ["/absolute/venv/bin/python", "/absolute/local/ansys_worker.py"],
  "capabilities": {
    "name": "fluent-local", "version": "site-tested-v1", "is_mock": false,
    "operations": ["domain.construct", "mesh.generate", "physics.configure", "solver.initialize", "solver.advance", "solver.stop", "results.extract"],
    "domain_strategies": ["extract"], "mesh_methods": ["tetra"],
    "turbulence_models": ["laminar"], "heat_models": ["isothermal"],
    "time_modes": ["steady"], "rotation_models": ["none"],
    "restart": true, "resource_limits_enforced": true
  }
}
```

这只是形状示例；`resource_limits_enforced=true` 只能在部署环境验证完成后启用。

默认 supervisor 面向带 `/proc` 和 CPU affinity 的 Linux：固定命令、无 shell、最小环境、继承 CPU 集合、单进程地址空间限额、进程组 RSS 轮询、文件增长/总输出检查、超时 killpg。
RSS 检查有约 50 ms 采样粒度，并非内核级总内存硬上限；特别严格的生产配额应使用 cgroup/container supervisor。
本地 Worker 必须可信且不得 `setsid` 逃离进程组。路径检查不是针对任意恶意原生程序的完整 OS 沙箱。

**Windows 原生 Ansys**：通过 `LocalWorkerBackend(..., supervisor=...)` 接入基于 Windows Job Objects 的本地 supervisor；拓扑 Worker 通过 `IsolatedOCAFTopology(..., supervisor=...)` 注入同等替代执行器。默认 supervisor 会返回 capability_gap，不会降级为无约束运行。许可证环境由本地 supervisor 显式配置，不从 Agent 输入/环境全量继承。

## 修复、预算与恢复

默认 `allowed_repairs=[]`。专家可以显式允许：

- `refine_mesh`：仅缩小 global/local size；不改变质量阈值、单元预算、几何或 BC。
- `reduce_relaxation`：仅减小 relaxation；不改变物理模型、收敛标准或迭代预算。

所有修复生成新 Spec 哈希、保存之前的状态与失败证据，并重新构造域/网格/设置；总迭代、时间、调用数继续累积。
拓扑歧义默认终止；自动重新选择只有在明确的新依赖/原生证明可用时才应由接入层提交新 Spec，不会猜面。

```python
record = runner.run(spec, job_id="case-a", pause_after="mesh")
record = runner.run(spec, job_id="case-a", resume=True)
replay = runner.run(spec, job_id="case-b")
```

- resume 校验原始 Spec、后端能力/版本、文件哈希与审计哈希链。
- solver 块从真实 checkpoint 继续，前提是后端声明并验证 restart。
- 同 job 存在 OS 文件锁，避免并行写入；暂停记录不是成功。
- 进程崩溃时，如果外部调用开始但完成状态不明确，返回 `uncertain_external_state`。先做本地状态核对，不能盲目重复消耗许可/计算；新 job 重放保留原记录。
- 取消在 bounded Worker 边界检查；一次长 Worker 调用最迟到其超时才被强制回收。不要把 `chunk_iterations` 配成整个漫长求解。
- 同一 Mock Spec 的指标确定；真实求解的数值重现性取决于网格、求解器版本、并行规模等，框架不声称 bitwise 一致。

## API / MCP

`CFDService` 提供 submit/status/cancel/resume 有界队列；服务重启后可从 job 检查点恢复。
默认一个 Worker；OCAF 并发场景使用子进程桥，不能跨线程共享原生 document。

```python
from seekflow_cfd.service import CFDService, register_mcp_tools
from seekflow_cfd.api import create_app

service = CFDService(orchestrator_factory, output_root, max_workers=1, max_pending=16)
app = create_app(service)  # pip install -e 'integrations/cfd[api]'
# register_mcp_tools(existing_mcp, service, prepared_topology, revisions=revision_bridges)
```

该片段的 factory/root/topology 由部署层提供。HTTP 端点为 `/cfd/schema`、`/cfd/jobs`、`/cfd/jobs/{id}`、cancel/resume。
没有直接暴露绕过状态机的 solver 执行端点。MCP 额外提供角色列表、resolve、export、跨 revision 比较。
部署层应沿用本地服务的身份验证/访问控制；不要将可消耗许可证的服务未经认证直接发布公网。

## 验证范围

- 纯软件 Spec/质量门/故障/预算/恢复/审计/Agent 合同测试。
- 原生 OCAF：含孔环模型 + 半径变化后的命名面解析、实际 BRep 导出。
- 已在本地 Fluent 18.1 上完成 D01 真实 STEP/XBF/history 输入的完整单点：
  domain、网格、物理设置、初始化、240 次迭代、停止和结果提取均成功；
  具体哈希、质量指标与结果见 `docs/自动CFD-D01真实全链路验证报告.md`。
- 未在这里运行 CFX；也没有宣称已完成榫槽/环槽流道的真实 CFD 网格与边界传递验收。
- 单次成功不能证明网格无关性；`mesh_independence` 至少需要 3 个同物理/同几何的真实成功记录，不虚构 GCI。
- 当前瞬态判断适用于趋于稳定终态的任务；持续非定常/周期统计、滑移网格接口等必须由本地后端提供更专门的验收能力，不能将残差窗口等同于所有瞬态问题都已验证。

详细需求映射和本次测试结果见 `docs/自动CFD仿真-架构与实施设计.md`（仓库根目录）。
