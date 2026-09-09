# 持久化拓扑命名：当前状态总结

> 最后更新：2026-08-17。本文档描述批次 1（edge 语义身份闭环）完成后的最新状态，供后续 agent 或开发者接手使用。

## 1. 目标

在复杂模型构建中，对任意面/边提供跨 revision 可靠、可持久化的拓扑命名，使 CAE 绑定和下游特征能够稳定引用拓扑身份，而不是依赖几何索引或启发式匹配。

## 2. 架构速览

系统建立在 OCAF/TNaming 之上，数据流如下：

1. `tracked_ops/*`：CadQuery 建模函数的 drop-in 替换，在构造几何的同时用 OCCT `History()/Generated()/Modified()/IsRemoved()` 捕获真实拓扑演化，产出 `LiveEvolutionBatch`。
2. `writer.py`：`TopologyNamingWriter` 把批次写入 OCAF 固定 Tag 树，用 `TNaming_Builder` 写 Generated/Modify/Delete，并为 face/edge role 维护 ResultRoot 下的稳定命名链。
3. `label_index.py`：`StableLabelIndex` 维护「业务 key → TagPath」的稳定映射，跨 revision 不因遍历顺序漂移。
4. `selection_service.py`：`PersistentSelectionService` 用 `TNaming_Selector` 创建和求解持久选择。
5. `pipeline/run.py`：把 canonical IR 的选择转成 `SelectionSpec`，在写入事务内创建选择，随后跑 CAE preflight 和子进程 verify。

关键源码目录：

```text
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf
integrations/engineering_tools/tests/generative_cad/topology/ocaf
```

核心身份原语：`SourceEntityRef`、`RelationKey`、`FaceRoleSpec`、`EdgeRoleSpec`。

## 3. 已完成能力

- OCAF XBF 的创建、保存、发布、重开，以及稳定索引的持久化与校验。
- tracked ops 覆盖：extrude、revolve、fillet、chamfer、boolean（cut/fuse/common）、shell、sweep、loft、linear/circular pattern、unify、mirror。
- 普通面逐面命名 `face_roles`，以及 fillet/chamfer 相邻面 Modify 链、boolean carry-through。
- 任意 edge role 基础设施。
- 后生成任意面/边选择。
- feature 级依赖闭包。
- CAE proof gate。
- C++ fixture：`ocaf_smoke`、`tnaming_smoke`、`edge_lineage`、`edge_boolean`、`full_edge_boolean`。

## 4. 批次 1 刚完成：edge 语义身份闭环

提交：`96a7db2 feat(ocaf): complete edge semantic identity (P1-1/P1-2/P1-3)`

本次完成内容：

- `models.py` 新增 `EdgeRoleSpec`，对称于 `FaceRoleSpec`，携带 `source_shape` 和 `first_evolution`。
- `writer.py`：`EDGE + GENERATED/MODIFIED` 路由到 JSON audit，`Feature/3` 成为纯 metadata；`_write_edge_roles` 支持用 `source_shape` 写 `Modify`/`Generated` 链。
- `boolean.py`、`pattern.py`、`revolve.py`：补上 `relation_key` 和 `source_ref`。
- `boolean.py`、shell、sweep、loft、pattern、revolve：产出结果边 `edge_roles`。
- 清理了 `offset_sweep.py` 里重复的 `face_roles` 初始化。

改动范围：7 个文件，`+240 / -21`。

## 5. 测试状态

全量 OCAF 测试结果：

```text
289 passed, 4 skipped, 1 failed
```

唯一失败 `test_abort_then_retry_succeeds` 是子进程启动时的 Windows 权限抖动，单独复跑通过，属于环境 flaky，与代码无关。

## 6. 剩余缺口

### P1-4：merge / delete / split 跨 revision 回归仍不完整

- split 已有跨 revision 回归。
- merge（N→1，即 unify）跨 revision 端到端回归仍缺。
- delete 的权威身份仍未完全落地：跨进程重开后，delete 判定仍依赖几何指纹，而不是通过 `SELECTION_TAG_SHAPE_ANCHOR` 的 original shape TShape 身份做权威比较。

### P2-1：OCP 多版本矩阵仍只有当前环境

- 目前只有 OCP `7.8.1.1`。
- `_p8_envs/ocp-7.8.1.0` 目录存在，但矩阵脚本尚未真正产出多版本对比。

### P2-2：非 role selection 依赖闭包仍偏保守

- face/edge selector 当前回退到 component terminal feature，无法解析时退到 component scope。
- 中游 feature 上任意面选择的最优 seed feature 尚未计算。

## 7. 提交与推送状态

- 本地 `main` 已包含批次 1 提交 `96a7db2`。
- 推送到 `text2cad/main` 未成功，原因是当前机器的网络/凭证环境：
  - 环境变量 `HTTP_PROXY` / `HTTPS_PROXY` / `GIT_HTTPS_PROXY` 等指向失效代理 `127.0.0.1:9`。
  - 清掉代理后，schannel 报 `SEC_E_NO_CREDENTIALS`。
  - 切到 openssl 后端报 `unable to get local issuer certificate`。

代码本身已完成并通过测试，推送仅被环境阻塞。

## 8. 建议下一步

1. 先恢复代理或配置好 GitHub 凭证，把 `96a7db2` 推送到 `text2cad/main`。
2. 然后进入批次 2：P1-4（merge/delete 权威跨 revision）+ P2-2（非 role 依赖闭包）。
3. 批次 3：P2-1（OCP 版本矩阵），作为独立环境工作。
