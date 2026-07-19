# PR 4 实施规划：Sketch Stable IDs

> **前置：Phase 1-6 + PR 7 已交付 (96 tests, 0 failures)**
> **核心：给 sketch element params 添加可选的 element_id + semantic_role**
> **约束：完全向后兼容，不破坏 existing extra="forbid" 行为**

---

## 0. 代码探查发现

### 当前 sketch element params（共 10 个）：

```python
# sketch_profile/params.py — 全部 extra="forbid", 没有 element_id
Create2dSketchParams  # 创建草图 (不需要 element_id — 它是容器)
AddLineSegmentParams   # 线段 — 需要 element_id
AddArcSegmentParams    # 圆弧 — 需要 element_id
AddCircleParams        # 圆 — 需要 element_id
AddPolylineParams      # 折线 — 需要 element_id
CloseProfileParams     # 闭合 — 不需要
ExtrudeProfileParams   # 拉伸 — 不需要
CutProfileParams       # 切割 — 不需要
AddSlotParams          # 槽 — 需要 element_id
LinearPatternParams    # 阵列 — 不需要
MirrorFeatureParams    # 镜像 — 不需要
RevolveProfileParams   # 旋转 — 不需要
FilletSketchParams     # 圆角 — 需要 element_id
```

### 关键约束

- 所有 params 都是 `ConfigDict(extra="forbid")` — 不给 element_id 就无法通过 params 传递
- `RawNode.params` 是 `dict[str, Any]` — LLM 可以放入 element_id
- 但 Pydantic 校验后会被丢弃（因为 extra=forbid）

---

## 1. PR 4 范围

### 修改文件 (2 个)

| 文件 | 修改 |
|---|---|
| `dialects/sketch_profile/params.py` | 对 5 个几何元素添加 `element_id: str \| None = None` + `semantic_role: str \| None = None` |
| `topology/semantic_naming.py` | 新增 `extract_sketch_element_ids()` — 从 canonical node 提取 element_id 列表 |

### 不修改

- `ir/raw.py` RawNode — params 已是 `dict[str, Any]`，无需变更
- `ir/canonical.py` CanonicalNode — 同上
- LLM prompts — 后续 Phase
- sketch_profile handlers — 后续 Phase

### 修改的元素 (5 个)

```python
class AddLineSegmentParams:  + element_id, semantic_role
class AddArcSegmentParams:   + element_id, semantic_role  
class AddCircleParams:       + element_id, semantic_role
class AddPolylineParams:     + element_id, semantic_role
class AddSlotParams:         + element_id, semantic_role
```

---

## 2. 实施顺序

```
4.1: sketch_profile/params.py — 5 个 params 模型加 element_id + semantic_role
4.2: topology/semantic_naming.py — extract_sketch_element_ids()
4.3: 运行全部测试确保零回归
4.4: 写入 PR 4 测试
```

## 3. 验收标准

- [ ] 5 个 sketch element params 有可选的 `element_id` 字段
- [ ] `extract_sketch_element_ids()` 从 canonical nodes 提取 element_id → semantic_role 映射
- [ ] 所有现有测试零回归 (params 向后兼容)
- [ ] element_id 为 None 时不影响现有行为
