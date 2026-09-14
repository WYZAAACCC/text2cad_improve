# CFD 真实网格质量门问题记录：D01 Fluent 单点网格

日期：2026-09-10
状态：已解决并完成真实全链路验证；保留失败与修复前的对比证据

## 1. 现象

选择已生成典型涡轮盘 D01（`model.step`，哈希
`08cf8b44db8735f2589cde6c7ead9282f6b8fe7007f6d5c9e75d59bc12020f8a`）作为
真实自动 CFD 的首个完整算例。采用矩形外域减去 STEP 实体的流体域、四面体
体积网格，并使用本地 ANSYS Fluent 18.1 的 `/mesh/quality` 与 `/mesh/check`
作为真实网格验收。

早期网格策略只把 `solid_wall` 表面尺寸设为 5 mm，外域其余表面没有尺寸场；
Fluent 报：

- 最小正交质量：约 `1e-4`；
- 大量长细四面体，最差单元集中在盘体圆角/盘缘处；
- `/mesh/repair-improve/improve-quality` 重复多次后仍只有约 `1e-3`。

增加 Gmsh Distance + Threshold 背景尺寸场、近固体 5 mm、远场 60 mm 后：

- Gmsh 四面体约 649,799 个；
- Fluent 最小正交质量提高到 `8.11091e-03`；
- 仍低于原 spec 门限 `0.05`。

## 2. 根因与边界

当前 D01 验证网格是 STEP 实体经过 OCC 布尔求差后生成的纯四面体网格。盘缘
与过渡处的局部几何曲率/汇合边会在近固体加密附近产生少量长细单元；纯四面体
把“最小正交质量 0.05”作为通过门限明显高于 Fluent 官方对通用网格的最低要求。
Fluent 18.1 自身只把“Minimum Orthogonal Quality below 0.01”作为警告门槛，
官方对一般单元网格的保守要求是最小正交质量大于 0.01，而不是 0.05。

因此科学验收不能简单地保留 0.05 后无限加密，也不能无依据地放松。处理原则：

1. 先继续改进真实网格（更平滑尺寸场、曲率自适应、优化器、边界层等）；
2. 若仍无法达到 0.05，在报告中记录 Fluent 官方阈值依据，并把 D01 验证 spec
   的质量门调整为可辩护的最低正交质量 `0.01`；
3. 任何阈值调整都必须同时保留“Fluent 不报告负体积、网格检查通过、正交质量
   平均值与最差值分布可复核”的证据，不能变成只要求软件不报错。

## 3. 需要保留的可复核产物

- 网格变体目录：`_cfd_experiment/output/dev/variants/`
  （`alg1`、`alg2`、`alg4`、`dist_alg4`，以及后续 `dist_curv`/`dist_fine`
  等）；
- Fluent 原始输出：`fluent_check.out`；
- Gmsh/网格质量证据：`gmsh_quality.json`；
- D01 job：`_cfd_experiment/output/dev/jobs/d01-smoke-*`。

## 4. 修复结果

最终采用：

1. Gmsh 从 STEP 构造外域并生成距离场四面体；
2. `solid_wall` 近壁尺寸 5 mm，远场按实测 clearance 平滑过渡；
3. Fluent 18.1 执行 10 遍 `/mesh/repair-improve/improve-quality`；
4. 在质量门之前写出修复后的 `mesh-final.cas.gz`。

D01 最终网格为 96,210 个四面体，Fluent 报最小正交质量为
`0.0683321`，最小单元体积为 `8.299787e-09 m3`，`/mesh/check` 未报告
负体积。因此没有再通过降低阈值绕过问题。

## 5. 后续状态

此文件只记录质量门问题与分析，不改变 CAD 生成主流程。后续真实求解阶段若
遇到新的边界条件/报告/收敛问题，应追加独立章节，不得用 Mock 或“照着答案
写结果”代替。

D01 的真实全链路结果、高 Re 失败边界和低 Re 收敛证据见
`docs/自动CFD-D01真实全链路验证报告.md`。
