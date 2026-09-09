# 模型对比表 V2（占位版，沿用此前确认口径）

- 说明：AeroDisk-LLM 暂用 DeepSeek v4-Pro 数据占位；
  论文原模型列表 Base-Coder / CAD-RAG / Qwen2.5-72B / DeepSeek-R1-Distill /
  Llama-3.3-70B 暂以实际完成的 GLM5.2 / DeepSeek v4-flash / Qwen3.7-Plus 替代。
- 口径沿用此前已确认的模型对比表：
  FinalSuccess@3 = 三轮修复内通过校验、CAD 执行与工程验证门；
  Engineering Pass@1 = 最终工程成功且 LLM 修复次数为 0。

| 模型（占位） | 参数识别准确率/% | FDG节点F1/% | FDG依赖边F1/% | Engineering Pass@1/% | FinalSuccess@3/% |
| --- | --- | --- | --- | --- | --- |
| AeroDisk-LLM（=v4-Pro，待替换） | 93.4 | 95.5 | 93.9 | 63.5（254/400） | 79.0（316/400） |
| DeepSeek v4-flash | 96.2 | 92.3 | 91.9 | 41.8（167/400） | 41.8（167/400） |
| GLM-5.2 | 96.1 | 94.3 | 93.1 | 58.5（234/400） | 60.8（243/400） |
| Qwen3.7-Plus | 95.2 | 86.0 | 85.7 | 27.0（108/400） | 27.0（108/400） |

## 当前新代码主实验（补充口径，勿混用）

当前 DeepSeek v4-Pro 新 400 次（含 fillet 规则层）使用“几何门”
（MCP + 体积/表面积 ≤1%）统计时：

| 模型 | Runs | 几何门成功 | Pass@1（几何门+零修复） |
| --- | --- | --- | --- |
| DeepSeek v4-Pro（占位 AeroDisk-LLM） | 400 | 390（97.5%） | 378（94.5%） |

历史 GLM-5.2 / v4-flash / Qwen3.7 批次不使用体积/表面积 1% 几何门，
仅报告其原始工程门口径（FinalSuccess@3 / Engineering Pass@1）。
若要并列报告，需要按同一代码版本重跑。

数据源：
- 原模型对比口径：`MODEL_COMPARISON_TABLE.md`、`paper_metrics_all.json`
- Qwen 汇总：`_qwen3_7_final_400/aggregate.json`
- 新主实验：`rerun_120_t1t40_3seeds*`、`rerun_40_t1t40_seed9`
