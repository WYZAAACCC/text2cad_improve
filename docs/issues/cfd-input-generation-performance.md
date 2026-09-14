# CFD 输入生成性能问题报告：D19-D32 拓扑束生成过慢

日期：2026-09-10

## 1. 现象

为生成 D01-D32 的 CFD 输入拓扑束（`model.step + design.xbf + history.json`），
使用 `.conda` 环境按 10 worker 并行运行：

```bash
python _param_experiment/turbine_disc_dataset_D01-D32/build_cfd_inputs.py \
  --family D19 ... --family D32 --workers 10
```

实测单族耗时约 32-90+ 分钟，明显高于简单盘族（D01-D13 约 0.5-2 分钟级）。
运行约 2 小时后仍未完成全部 14 族，用户要求停止并排查根因。

停止时状态：

| 状态 | 设计族 |
| --- | --- |
| 已完整生成 | D19、D23、D24、D25、D26、D27、D29 |
| 未完整生成 | D20、D21、D22、D28、D30、D31、D32 |

## 2. 直接证据

- D19 canonical IR 中榫槽 pattern 数量为 60；
- D21 canonical IR 中榫槽 pattern 数量为 84；
- D24 canonical IR 包含 48 槽 pattern + 16 孔 pattern + 环槽布尔；
- 已完成的 XBF 标签规模很大：D24=54,061，D19=74,715，
  D26=77,609，D25=81,273；
- 对同一族的 STEP 写出时刻与 history 写出时刻对比，最后 XBF 发布/校验阶段通常
  只占约 5-9 分钟。主要耗时位于 STEP 之前的几何执行与实时拓扑捕获阶段。

## 3. 根因

慢点不是最终 OCAF 序列化，而是“槽/孔阵列的实时拓扑捕获”采用逐实例顺序融合，
并对每个实例做全量面/边历史扫描，复杂度随数量呈超线性增长。

### 3.1 执行路径

1. 捕获开启时，组合层的
   `dialects/composition/handlers.py: handle_circular_pattern_component`
   将 `circular_pattern_component` 路由到
   `topology/ocaf/tracked_ops/pattern.py: tracked_circular_pattern`。

2. `tracked_circular_pattern` 对 N 个实例执行 N-1 次顺序
   `BOPAlgo_BOP + BOPAlgo_FUSE`。融合对象是从单个槽/孔逐步增长为 N 个实体的
   整个体，因此每步的体复杂度都在增长。

3. 每次融合后，代码遍历当前目标体和工具体的所有面/边，调用 OCCT history：

   - `Generated(face)`
   - `Modified(face)`
   - `IsRemoved(face)`

   对边也执行同样流程。

4. 分离实例融合时 OCCT history 常不报告 carry-through；代码因此逐个调用
   `_find_partner_face()` / `find_partner_edge()`，其实现为对结果体的全部面/边
   做线性扫描。这一步等效为：

   - 每一步扫描 O(当前实体数 x 每实例面数) 的输入面；
   - 对每个未变化的输入面再扫描 O(结果体面数) 的面列表。

   随 N 增大，总拓扑匹配次数近似 O(N^2)-O(N^3)。

5. 融合完成后还会调用
   `topology/ocaf/tracked_ops/pattern.py: HistoryGraph.from_relations()`，
   并用 `HistoryComposer` 对每个种子面做前向追踪；`HistoryGraph.successors()`
   对每个待追踪 shape 又线性扫描全部 history 边。

6. 最终对盘体的 `tracked_cut()` 复用 `tracked_ops/boolean.py: _export_bopalgo_history()`，
   再次对盘体与完整 cutter pattern 的每个面/边执行同类全量扫描与 carry-through
   匹配，因此同一问题在最终布尔阶段再次出现。

### 3.2 为什么 D19-D32 最严重

D19-D22 为 60/72/72/84 槽的 3-4 齿榫槽盘；
D23-D28 在榫槽基础上叠加 12-24 孔与 1-2 道环槽；
D29-D32 再叠加厚轮缘与复杂轮缘过渡。所有大数量阵列都进入上述 pattern 路径，
所以单族需要大量 BOPAlgo 调用和越来越大的拓扑历史关系集。

## 4. 影响与边界

- 该问题不影响 D01-D18 已生成产物；
- 该问题不是 D29-D32 几何脚本本身错误，而是拓扑捕获实现策略的复杂度；
- 已停止的并行任务没有残留 Python worker。

## 5. 建议修复方向

1. 为槽/孔阵列改用索引化 partner 查找，避免每个 carry-through 面都线性扫描
   结果体全部面/边；
2. 评估“单次 BOPAlgo 多 tool 布尔”或批量分组切割，避免 N-1 次全量融合；
3. 对 pattern 历史图查询建立 shape 哈希索引，避免 `HistoryGraph.successors()`
   每次线性扫描全部 history；
4. 修改前先以 D19 或 D21 做单族基准，对比几何哈希、XBF 标签数量与运行时间，
   确认不改变结果后再考虑全量重跑。

本文档只记录问题与分析，不改变生成主流程。

## 6. 已实施优化与验证

日期：2026-09-10

已实施两项不改变几何语义的优化：

1. `tracked_linear_pattern` / `tracked_circular_pattern` 将 N-1 次顺序
   `BOPAlgo_FUSE` 改为一次多 tool `BOPAlgo_FUSE`。阵列仍保持 union 语义，
   并保留 overlap/连通性回退：若一次 fuse 后的独立实体数不再等于实例数，
   自动回退到原逐实例顺序 union。
2. carry-through partner 查询改用 `TopTools_IndexedMapOfShape` 原生拓扑索引，
   避免每个面或边都重新线性扫描整个结果体。该索引同时用于 boolean history
   导出的 face/edge carry-through 匹配。

验证方法不是只比较运行时间，而是对同一 canonical IR 重建后，与优化前已有
CFD 拓扑束逐项比较：

| 族 | 实体数 | 面数 | 边数 | 体积 | 表面积 | XBF 标签数 | XBF 大小 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D05 | 一致 | 一致 | 一致 | 0 差异 | 0 差异 | 4917 = 4917 | 2.194 MB = 2.194 MB |
| D15 | 一致 | 一致 | 一致 | 0 差异 | 0 差异 | 37631 = 37631 | 16.265 MB = 16.265 MB |
| D19 | 一致 | 一致 | 一致 | 0 差异 | 0 差异 | 74715 = 74715 | 32.312 MB = 32.312 MB |

同时比较了 XBF 的稳定索引内容：D05、D15、D19 的
`object_kind + namespace + object_id + tag_path + revision` 集合与优化前完全一致，
差异数为 0。D19 新 bundle 的 8 个持久 role 也全部解析到同一最终面，面积相对误差
和质心误差均为 0。

优化后单 worker 实测：

| 族 | 总耗时 | canonical → STEP | STEP → XBF 发布 |
| --- | --- | --- | --- |
| D05 | 10.8 s | 约 4 s | 约 2 s |
| D15 | 113.6 s | 约 46 s | 约 60 s |
| D19 | 416.1 s | 约 156 s | 约 252 s |

D19 优化前已有时间戳记录为 canonical → STEP 约 82 分 40 秒，STEP → XBF
约 8 分 48 秒。优化后对应阶段分别降至约 2 分 36 秒和 4 分 12 秒。

剩余瓶颈与边界：

- D19 的 XBF 仍有约 74,715 条稳定索引、32 MB，OCAF 写入/保存/发布约 4 分钟；
  这部分没有通过本次布尔优化消失，因为最终实体、面角色和边角色规模没有改变。
- 不要为了缩短 XBF 而直接删除 role/relation 标签；必须先证明拓扑身份、跨
  revision Solve 和 CFD 选面仍可唯一恢复。任何“减少标签”的改动都应单独做 A/B
  对照，验收标准是实体几何、面/边数量、role 唯一解析和选择结果全部一致。
- 多版本 lineage 当前仍是每个 revision 从 canonical 重新完整构建，尚未实现
  canonical feature DAG 脏区重算或子树缓存。若后续需要把同 lineage 参数扰动
  压到 10-20 分钟以内，应在上述几何等价门通过后再实现增量重算。
