# 持久化拓扑命名：当前进度与剩余缺口

> 本文档用于交接给下一个 agent。目标是“复杂模型下任意面/边的可靠持久化拓扑命名”。

## 1. 当前实现进度

### 1.1 已闭环能力

- OCAF XBF 创建、保存、发布、重开。
- 稳定标签索引（component / feature / selection / relation / face_role / edge_role）。
- tracked ops：
  - extrude
  - revolve
  - fillet
  - chamfer
  - boolean cut / fuse / common
  - shell / sweep / loft
  - linear / circular pattern
  - unify
  - mirror
- 普通面命名 `face_roles`。
- 任意 edge role 的基础设施。
- 后生成任意面 / 边选择。
- 特征级依赖闭包。
- CAE proof gate 结构化。
- C++ 原生 fixture：
  - ocaf_smoke
  - tnaming_smoke
  - edge_lineage
  - edge_boolean
  - full_edge_boolean

当前全量测试结果：

```text
291 passed, 1 deselected
```

## 2. 关键路径

主要代码目录：

```text
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf
integrations/engineering_tools/tests/generative_cad/topology/ocaf
```

核心文件：

- `models.py`
- `writer.py`
- `selection_service.py`
- `label_index.py`
- `document.py`
- `tracked_ops/*.py`
- `pipeline/run.py`

C++ fixture：

```text
integrations/engineering_tools/tests/generative_cad/topology/ocaf/cpp_fixture
```

## 3. 剩余缺口

### P1-1：EDGE relation 尚未完成最终迁移

现状：

- FACE `GENERATED/MODIFIED` 已写 JSON audit，不再写 TNaming。
- `DELETED` 保留 TNaming，并已写 JSON audit。
- EDGE `GENERATED/MODIFIED` 仍然写 TNaming。

目标：

- EDGE relation 应迁移到 edge role 体系；
- `Feature/3` 应成为纯 JSON metadata。

涉及文件：

- `writer.py`
- `tracked_ops/boolean.py`
- `tracked_ops/offset_sweep.py`
- `tracked_ops/pattern.py`

### P1-2：SourceEntityRef / RelationKey 仍有覆盖盲区

已接入：

- fillet
- chamfer
- unify
- mirror
- boolean 主要 face relation
- sweep / loft / shell
- pattern 最终 face role

仍未完全接入：

- boolean 的 edge relation 与部分 carry-through relation
- pattern 的 instance / fuse 中间 relation
- revolve 的普通面 relation

目标：

- 所有 tracked op 的 relation 使用 `relation_key`；
- 所有 face role 使用 `source_ref`。

涉及文件：

- `tracked_ops/boolean.py`
- `tracked_ops/pattern.py`
- `tracked_ops/revolve.py`

### P1-3：Edge role 覆盖仍不全

已覆盖：

- box extrude 12 条边
- fillet / chamfer 输入边

仍未覆盖：

- boolean 结果边
- shell / sweep / loft 结果边
- pattern 结果边
- revolve 结果边

目标：

- 复杂操作结果边也拥有稳定 edge role。

涉及文件：

- `tracked_ops/boolean.py`
- `tracked_ops/offset_sweep.py`
- `tracked_ops/pattern.py`
- `tracked_ops/revolve.py`

### P1-4：merge / delete / split 跨 revision 回归仍不完整

已新增：

- split 跨 revision 回归。

仍缺少：

- merge N→1 跨 revision；
- delete 跨 revision 权威身份。

当前 delete 仍主要依赖几何指纹，不是完全权威 original shape 身份。

### P2-1：OCP 多版本矩阵仍只有当前环境

当前：

- 只读取到 OCP `7.8.1.1`；
- C++ fixtures 可运行。

目标：

- 增加至少一个其他 OCP/OCCT 版本；
- 生成多版本对比矩阵。

### P2-2：非 role selection 依赖闭包仍偏保守

当前：

- face / edge selector 使用 component terminal feature；
- 无法解析时回退 component scope。

目标：

- 多组件 / 跨组件依赖的精确闭包；
- 中游 feature 上任意面选择的最优 seed feature。

## 4. 建议执行顺序

```text
P1-1 EDGE relation 迁移
   ↓
P1-2 身份键补全
   ↓
P1-3 edge role 覆盖补全
   ↓
P1-4 硬场景跨 revision 回归
   ↓
P2-1 多 OCP 版本矩阵
   ↓
P2-2 非 role 依赖闭包优化
```

## 5. 验收标准

全部完成后：

- 所有 tracked ops 使用语义身份键；
- 所有复杂操作边都有稳定 edge role；
- `Feature/3` 完全符合 JSON metadata schema；
- merge / delete / split 跨 revision 全通过；
- C++ `full_edge_boolean` 可运行；
- 多 OCP 版本矩阵生成；
- 全量 OCAF 测试通过并推送。
