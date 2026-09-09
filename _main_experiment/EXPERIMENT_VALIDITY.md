# 主实验科学有效性说明

本文档记录主实验数据采集的协议、已修复的正确性问题，以及必须向审稿人披露的边界。

## 1. 实验协议

- 基准：40 任务（L1 8 / L2 10 / L3 12 / L4 10；32 生成 + 8 编辑；8 个留出设计族）。
- 规模：每种方法 40 任务 × 10 随机种子 = 400 次独立运行。
- 配置：temperature=0.3、top-p=0.9、max_tokens=8192、CAD 单次 900s、任务 3600s、最多 3 轮修复。
- 每次运行记录：record_id、collected_at、schema_version、usage、时间戳、修复轮数、失败分类、全部中间产物。

## 2. 已修复的正确性问题（本仓库历史审计）

1. seed 之前只改 run 目录、未传 LLM 采样 → 已修复：每次运行以 `llm.copy(seed=seed)` 构造配置，agentic 工具循环与 repair 循环均携带 seed 调用。
2. agentic 分支缺少论文协议的 L1 路由步骤 → 已补：先执行 L1 并落盘 route_plan.json，计入 token。
3. FDG 节点/边 F1 恒为 0（组件命名差异、producer_node/node 键差异）→ 已修复。
4. agentic 分支漏写 validation_initial.json → 已补。
5. token 用量恒为 0 → 已修复（usage 回传）。
6. 几何尺寸测量 bug：generate_quality_report 的 measurements 是工具名列表 → 已从 details 取值。
7. 聚合曾读 run.json 内嵌旧指标 → 已改为优先读最新 metrics.json。
8. 关键尺寸相对误差曾用绝对 mm → 已改为相对百分比。
9. 新增体积/表面积相对误差：直接测量最终 STEP 实体并与 golden STEP 对比。
10. 参数识别准确率改为“用户需求参数 vs 模型实测值”映射比对，不再用两份 IR 的键交集。

## 3. 已确认有效的机制

- 40 任务构成与论文一致；golden 由确定性参数化模板生成且通过 MCP 门。
- Pass@1 = 零修复且首轮成功；FinalSuccess@3 = ≤3 轮修复内通过；CAD Pass@1 = Pass@1 且产出 STEP。
- runner 支持断点续跑；输出统一 records/manifest/report 格式。
- 失败分类（llm/validation/runtime/mcp_gate）与修复轮次逐条落盘。

## 4. 必须披露的边界

1. 模型口径：当前结果是“当前 agentic harness + DeepSeek-v4-pro”，不是论文的 AeroDisk-LLM（QLoRA 微调）。
2. 参考 golden 由参数化模板自动生成，不是独立专家建模；本基准衡量“agent 与模板一致性”，与论文“专家确认参考”不同。
3. 8 个编辑任务目前是文本式编辑（prompt 写“保持原有主体结构”），未向 agent 注入既有模型实体。
4. 关键尺寸/孔/槽参数测量来自修复后 IR；体积/表面积来自最终 STEP；bore 内径、槽深等未做独立截面测量。
5. seed 已传给 API；DeepSeek 服务端是否严格保证 seed 确定性需实测，记录 seed 用于追踪，复现性取决于服务端。
6. 榫槽 worker 存在 LLM 级波动（部分 L3/L4 任务偏差），按真实结果记录。
7. 商业 CAD 导入、专家一致性、训练类实验不在本环境，不混入主实验。
8. T24（D28 耦合变体）曾因孔 PCD=210、Ø14 使孔外缘（217mm）切入轮缘内壁（215mm），
   与环槽布尔产生 0.0085mm 数值细缝；已微调任务参数 PCD=205（外缘 212mm < 215mm），
   golden 全门通过。该任务在参数调整前采集的 10 次运行无效，需重跑。

## 5. 已知可靠性边界（T16 / T21）

- T16（D14 锥形环槽）：根因是基准 prompt 缺“锥形腹板”信息 + legacy autofix
  `fix_slot_half_profile` 误把 groove_cutter 当榫槽半剖面镜像合并轮廓。两处均已修复
  （任务文本补形态标签；autofix 只作用于榫槽 cutter 且点数 ≥5）。修复后真实运行 2/2 通过。
- T21（large_hub 槽盘）：剩余边界为 Agent C 榫槽 worker 的 LLM 可靠性——偶发
  自写近似算法（半宽偏大/点数错误）或直接留下占位点，且 repair 层无法归因
  （0 candidate nodes / 补丁重复）。已修正 prompt 中“参数即坐标”的自相矛盾表述，
  但该任务仍标记为已知可靠性边界，按真实结果记录，不做掩盖性修复。

## 5. 复现步骤

```text
python -m _main_experiment.cli golden
python -m _main_experiment.cli run --method-id full_agentic --agentic --seeds 0,1,2,3,4,5,6,7,8,9
python -m _main_experiment.cli aggregate
python -m _main_experiment.cli report
```

正式采集前记录代码 commit 与配置快照；采集期间冻结代码，保证 400 次可比。
