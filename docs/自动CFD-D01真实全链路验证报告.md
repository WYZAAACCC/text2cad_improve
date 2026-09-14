# D01 涡轮盘真实自动 CFD 全链路验证报告

日期：2026-09-10

## 1. 结论

系统已使用 D01 已生成涡轮盘的真实 `STEP + XBF + history` 输入，在本机
ANSYS Fluent 18.1 上完成一次非 Mock 的完整闭环：

`domain.construct -> mesh.generate -> physics.configure -> solver.initialize -> solver.advance -> solver.stop -> results.extract`

最终记录为 `success`，共推进 240 次迭代。第 238-240 次迭代窗口同时满足残差、
质量守恒和监测量稳定性要求。该结果证明当前受限能力范围内的真实自动 CFD
链路已经跑通；不表示已经覆盖任意涡轮盘工况、湍流、瞬态或工程标定。

## 2. 输入与身份

| 项目 | 值 |
| --- | --- |
| 设计族 | D01 |
| CAD revision | `rev-000001` |
| STEP SHA-256 | `08cf8b44db8735f2589cde6c7ead9282f6b8fe7007f6d5c9e75d59bc12020f8a` |
| XBF SHA-256 | `c14adebd41057b78eedcd831067eca136c049e706d9999f6ad4002eff68a7f8d` |
| history SHA-256 | `f09f1bde18e938fc956b139683c615b4e813dcec21aa23a313b1571b27c84c7a` |
| Spec SHA-256 | `4027dbf1bb2a856261234431cf0942246792534c7edbf97b386330a3f65fe191` |
| job | `_cfd_experiment/output/dev/jobs/d01-steady-lowre-1` |

## 3. 真实域与网格

流体域为显式矩形外域减去 D01 实体，网格由 Gmsh OCC/四面体和 Fluent 原生
转换生成。固体壁面作为独立 `disc_wall` zone 保留。

网格策略：

- 全局最大尺寸：60 mm；
- 固体壁面距离尺寸场：近壁 5 mm；
- 尺寸场过渡距离由实心体到外域边界的实测 clearance 计算；
- Fluent 18.1 内置 `/mesh/repair-improve/improve-quality` 执行 10 遍；
- 最终 `mesh-final.cas.gz` 在质量门之前落盘。

最终真实网格证据：

| 指标 | 值 |
| --- | ---: |
| 四面体单元数 | 96,210 |
| 最小正交质量 | 0.0683321 |
| 最大正交偏斜代理 | 0.9316679 |
| 最小单元体积 | `8.299787e-09 m3` |
| 负体积单元 | 0 |
| 六个外边界和盘面 zone | 全部保留并可配置 |

说明：早期只用表面尺寸的网格最小正交质量约 `1e-4`，距离场网格约
`8.11e-3`；Fluent 内建修复后达到 `6.83e-2`，因此没有把质量门降低到
“只要求软件不报错”。

## 4. 物理算例与失败边界

曾先用 `Z` 向来流进行 0.4 m/s 的横向绕流验证。真实求解运行到 300 次迭代，
质量守恒和网格检查正常，但盘后分离/反向流使定常层流残差停在约 `3e-2`，
未通过收敛门。该失败记录保留在
`_cfd_experiment/output/dev/jobs/d01-real-full-3`。

复核 D01 的真实坐标后确认盘体轴向是全局 `Y`，因此正式验证采用：

- 轴向来流：`+Y`；
- 入口速度：0.004 m/s；
- 出口：0 Pa gauge，压力出口；
- 物理模型：稳态、不可压缩、等温、层流；
- 初始条件：Fluent flow initialization；
- 最大迭代：300，分块 20 次，每个样本都保留边界通量、残差和监测值。

这个低 Re 算例明确标注为软件集成验证，不是涡轮盘设计预测。高 Re 横向绕流
失败没有被改写或删除，用来界定当前稳态层流能力的适用范围。

## 5. 收敛与结果

| 指标 | 值 |
| --- | ---: |
| 总迭代数 | 240 |
| 守恒窗口 | 238-240 |
| 连续性残差是否通过 | 是 |
| 速度残差是否通过 | 是 |
| 质量守恒相对误差 | `1.7006802437656522e-08` |
| 监测量是否稳定 | 是 |
| 出口质量流 | `-0.0058800002 kg/s` |
| 出口平均压力 | `101325.0 Pa` |
| job 实际耗时 | 502.406 s |

原始证据：

- `record.json`：完整记录与结果；
- `events.jsonl`：带哈希链的工具调用事件；
- `solver/advance-*.out`：逐块 Fluent 原始日志；
- `residuals.csv` / `residuals.svg`：逐迭代残差；
- `convergence.json`：守恒、残差、监控量和物理时间判定；
- `checkpoint-000240.cas.gz` / `.dat.gz`：最终 checkpoint；
- `postprocess/extract.*`：独立回读后的结果提取文件；
- `manifest.json`：全部产物的 SHA-256 清单。

## 6. 真实 LLM 专家审查

在数值结果保持不变的前提下，使用 `deepseek-v4-pro` 对同一 Spec 和同一
`record.json` 做了独立专家审查。五类专家——
`geometry_topology`、`domain_mesh`、`physics_boundary`、`solver_monitor`、
`verification_report`——对运行前 Spec 均返回 `accept`。

首次结果审查独立提出了四类证据问题：入口流量摘要缺失、单网格不能证明网格
无关性、等温算例没有激活能量方程、固定压力出口值不是独立预测。该
`needs_input` 记录也已保留，不修改或删除。

随后只补充由现有逐迭代样本直接计算的边界通量摘要和适用范围说明，再次执行
结果审查。最终结果审查返回 `accept`，理由是：

- 入口 `+0.00588 kg/s`、出口 `-0.0058800002 kg/s`、壁面近似零；
- 净质量不平衡约 `2e-10 kg/s`，相对误差 `1.70e-08`；
- 残差、守恒、监控量窗口均通过；
- 单网格和等温能量方程状态被明确标注，不再被误当作已完成物理标定。

完整调用轨迹和模型输出保存在
`_cfd_experiment/output/dev/agent_reviews/d01-steady-lowre-1.json`。
LLM 只在结构化审查层工作，没有进入 Solver、没有生成或执行 TUI/脚本，也没有
修改 Spec 和数值结果。

## 7. 尚未宣称的能力

- 未做三个以上网格的网格无关性研究，当前记录明确为
  `mesh_independence.verified=false`；
- 未完成湍流、旋转、瞬态、共轭传热和商业 CAD 前置导入；
- 未将低 Re 集成算例宣称为涡轮盘设计工况；
- 未使用 Mock 或硬编码结果替代任何真实求解值；
- D05 复验没有通过质量门：在 5 mm 近壁尺寸下，孔/槽小特征生成了 129,160
  个四面体，Fluent 最小正交质量仅 `1.19948e-03`；进一步减小尺寸和更换
  Delaunay 算法都没有在无额外验证的情况下达到 0.05。该失败记录保存在
  `_cfd_experiment/output/dev/jobs/d05-steady-lowre-1`，说明 D05 等含更多
  小特征的设计族需要专门的孔/槽尺寸场策略，不能把 D01 的结果外推。
- 当前成功是 D01 受限算例的真实单点验收，后续需要扩展到 D05 等其它已生成
  设计族，并在真实 D19-D32 拓扑上重新验证域/边界传递。
