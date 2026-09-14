# D19 自动选面到 Fluent 边界验证报告

日期：2026-09-10

## 1. 验证目标

验证 Agent 能否从 D19 最终盘体的数千个面中选出正确的工作齿面，并把精确
BRep 面唯一传递到真实 Fluent 流体域边界。

本报告只验证“选面到域边界”的工程接口，不代表已经完成 D19 的 CFD 求解。

## 2. 最终盘体统计

| 项目 | 值 |
| --- | ---: |
| 最终实体 | `n_final_cut`，单个 solid |
| 最终实体面数 | 3,910 |
| 工作扇区 | 3°-9° |
| 选定面 | 8 |
| 对称工作齿面对 | 4 |
| 径向法向符号 | 负，指向盘轴内侧 |

Agent 最终选择：

```text
17, 25, 33, 41, 53, 61, 69, 77
```

确定性选择验证要求：

- 全部为平面；
- 轴向导数为零；
- 径向法向同号；
- 每个面存在切向法向相反、面积相近的对称伙伴；
- 排除相对侧的非工作齿面、圆角和轴向端盖。

## 3. BRep 到 Fluent 边界

每个面独立导出为 BRep，并记录当前 revision、几何哈希、面几何事实和 BRep
SHA-256。Fluent Worker 的转移规则为：

1. 先按面积、质心和包围盒做快速预筛选；
2. 只对预筛选候选计算 OCC 最短距离；
3. 必须存在且仅存在一个满足全部容差的边界；
4. 0 个或多个候选都直接失败，不回退到最近面。

结果：

| 项目 | 值 |
| --- | ---: |
| 流体域边界总数 | 3,910 |
| Agent 选面边界 | 8 |
| `remaining_disc_wall` | 3,902 |
| 未覆盖面 | 0 |
| 每个选面的目标 boundary 数 | 1 |
| 转移 proof | `exact_brep_transfer` |

选面与目标 boundary：

| face | target |
| ---: | --- |
| 17 | `gmsh-face:18` |
| 25 | `gmsh-face:26` |
| 33 | `gmsh-face:34` |
| 41 | `gmsh-face:42` |
| 53 | `gmsh-face:54` |
| 61 | `gmsh-face:62` |
| 69 | `gmsh-face:70` |
| 77 | `gmsh-face:78` |

## 4. 当前限制

- 当前选择身份为最终实体 `solid_index=0` 加当前 revision 的临时面索引；
- 跨 CAD revision 的持久 `face_role/selection` 映射尚未完成；
- `exact_brep_transfer` 是严格唯一几何转移，不宣称为 OCAF 原生 history；
- 尚未对 D19 执行真实 Fluent 网格质量门、求解和收敛验证。

## 5. 证据

- 选择输出：`_structural_experiment/output/D19_final_face_intent_v3.json`
- 网格映射：`_structural_experiment/work/D19_mesh/selected_face_nodes_final.json`
- BRep 导出：`_structural_experiment/work/D19_final_selected_brep/selected_faces.json`
- 域构造响应：`_structural_experiment/work/D19_final_selected_brep/domain.response.json`
- 转移审计：`_structural_experiment/work/D19_final_selected_brep/domain_selection_transfer.json`
- 紧凑摘要：`_structural_experiment/work/D19_final_selected_brep/domain_transfer_summary.json`

## 6. 持久角色复核

后续已建立独立的 face-evolution SQLite 索引：

- `canonical_faces`：3,910 个最终面；
- `n_final_cut` face_role：19,473 条成功写入；
- 其中 3,897 条能解析为当前最终面；
- 15,576 条 generated role 实际是 edge/vertex 历史，不作为面候选；
- relation 元数据：23,620 条。

Agent 通过分页搜索和对称面候选选择后，提交了 8 个最终面和 8 个持久 role。
独立 verifier 在同一 OCAF session 内重新解析这些 role，结果全部与提交面
`IsSame`，面积和质心误差均为 0。

持久 role 导出后的 Fluent 域构造结果：

| 指标 | 值 |
| --- | ---: |
| 持久 role 数 | 8 |
| 独立 Fluent boundary | 8 |
| `remaining_disc_wall` | 3,902 |
| 未覆盖面 | 0 |
| 转移 proof | `exact_brep_transfer` |
| 持久状态 | `persistent_role_resolved` |

相关文件：

- 索引：`_structural_experiment/work/D19_face_evolution_v1.sqlite`
- Agent 选择：`_structural_experiment/output/D19_evolution_face_selection.json`
- role 实时验证：`_structural_experiment/output/D19_role_selection_verification.json`
- 持久 role BRep：`_structural_experiment/work/D19_persistent_role_brep/selected_roles.json`
- 域构造摘要：`_structural_experiment/work/D19_persistent_role_brep/domain_transfer_summary.json`

## 7. 跨 revision 复验

13 条此前因 carry NamedShape 崩溃而隔离的 role 已通过
`target_carry_shape_match` 恢复，3,910 个最终面现在全部有可解析的 face-level
role。`n_pattern_cutters` 源面索引也已改用真实结果形状建立，包含：

- 60 个实体；
- 4,080 个实际源面；
- 4,012 条 pattern relation 元数据。

跨 revision 复验使用真实 `run_lineage_revisions`：

- rev-000001：原始 D19 canonical IR；
- rev-000002：榫槽 cutter 截面宽度扰动 2%，拓扑保持不变。

同一个 Agent 选出的 8 个 role ID 在两版中分别原生解析：

| 指标 | 结果 |
| --- | ---: |
| 成功复解 role | 8/8 |
| 面类型变化 | 0 |
| 面积相对变化范围 | 0.795%-1.648% |
| 最大质心移动 | 0.130 mm |
| 法向绝对点积最小值 | 0.99995 |
| 验证状态 | `accepted` |

证据：

- `_structural_experiment/output/D19_carry_role_recovery.json`
- `_structural_experiment/output/D19_cross_revision_verification.json`
- `_structural_experiment/work/D19_cross_revision/revision_build_summary.json`
