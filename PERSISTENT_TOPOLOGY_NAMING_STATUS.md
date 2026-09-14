# 持久化拓扑命名：当前状态总结（已废弃）

> ⚠️ **本文档已废弃，请勿据此判断完成度。**
>
> 最新状态见 **[SYSTEM_STATUS.md](SYSTEM_STATUS.md)** 第 3 节。

## 为什么废弃

本文档最后更新于 2026-08-17，描述的是提交 `96a7db2` 时的状态。仓库此后又推进了 5 个提交：

```
43d2bc9  fix(ocaf): complete pattern result-face naming; add ultra-complex stress test tool
053a03d  fix(ocaf): complete record coverage for fillet/chamfer/mirror/unify (G6/G7)
62d8827  fix(ocaf): complete face/edge record coverage for all tracked ops (G1-G5)
52d4c21  test(ocaf): enforce unique-and-correct resolution with identity assertions
135247f  test(ocaf): complex-model persistence suite with run monitor and oracle checks
8f5f5b2  feat(ocaf): OCP multi-version matrix and parameterized C++ fixture (P2-1)
d187c82  feat(ocaf): authoritative delete identity and precise non-role seed (P1-4/P2-2)
```

本文档中的剩余缺口判断与测试数字均已过期：

| 本文档的说法 | 代码实际 |
|---|---|
| P1-4 merge / delete 跨 revision 未完成 | **已完成**。delete 已改为权威 TShape 比对（`selection_service._read_shape_anchor()` 读 `SHAPE_ANCHOR` 的 original shape 做 `IsSame/IsPartner`，几何指纹退为 fallback）；merge / split 跨 revision 测试齐备 |
| P2-1 OCP 多版本矩阵未产出 | **部分完成**。Python/OCP 侧 3 个解释器全绿（7.8.1.1 / 7.8.1.0 / 7.9.3.1）；仅 C++/OCCT 侧仍为单版本 |
| P2-2 非 role 依赖闭包偏保守 | **已完成**。`pipeline/run.py:_resolve_feature_for_shape()` 逆序定位真正生产该 shape 的 feature，并用 `_is_carry_through()` 排除纯透传 |
| 测试 `289 passed, 4 skipped, 1 failed` | **实测 `320 passed, 0 failed, 0 skipped, 0 deselected`**（2026-09-10，耗时 4 分 50 秒） |
| flaky 用例 `test_abort_then_retry_succeeds` | 本次 PASSED |
| §7 推送受阻（代理 / 凭证问题） | 已无意义，本地 `main` 已领先到 `606ab55` |

## 同时请勿依赖

`PERSISTENT_TOPOLOGY_NAMING_GAPS.md` —— **该文档已删除**。它把 P1-1 / P1-2 / P1-3 全列为待办，
而这三项在同一批次的 `96a7db2` 就已闭环。

## 真实残留缺口（仅两项）

1. C++/OCCT 侧仍只有单版本（OCCT 7.8.1）
2. 多组件 / 跨组件依赖闭包仍偏保守

---

完整现状、实测证据与关键路径速查见 **[SYSTEM_STATUS.md](SYSTEM_STATUS.md)**。
