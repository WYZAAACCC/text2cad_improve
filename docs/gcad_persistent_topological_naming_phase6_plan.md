# Phase 6 实施规划：CAE NamedTopologySet Bridge

> **前置：Phase 1-5 + PR 7 已交付 (88 tests, 0 failures)**
> **约束：当前环境无 ANSYS → 不修改 fea_pipeline.py 和 APDL templates**
> **策略：构建 CAE bridge 模块 + NamedTopologyRef 数据模型 + preflight gate**

---

## 0. 代码探查发现

### 当前 CAE 几何引用方式

```python
# fea_models.py — RegionDef 使用坐标范围选面
class RegionDef(BaseModel):
    region_id: str
    r_mm: float | None = None      # "选 R≈60 的面"
    z_mm: float | None = None      # "选 Z≈0 的面"
    r_min/r_max/z_min/z_max        # 范围容差
```

**问题**：坐标范围不能区分同一 R 的不同语义面（如 bore 内壁 vs hub 外壁）。

### 目标引用方式

```python
# NamedTopologySet — 使用持久拓扑 ID
NamedTopologySet(
    name="disk.center_bore.wall",
    persistent_ids=["gct:v1:doc:disk:revolve_1:center_bore:face:hole_wall"],
    semantic_purpose="constraint",
)
```

---

## 1. Phase 6 范围

### 新增文件 (1 个)

| 文件 | 内容 |
|---|---|
| `topology/cae_bridge.py` | CAE bridge: resolve topology sets → faces + preflight gate + load/constraint policies |

### 修改文件 (2 个)

| 文件 | 修改 |
|---|---|
| `topology/policies.py` | CAE policy 强制执行 |
| `topology/__init__.py` | 导出 cae_bridge |

### 不修改

- `fea_pipeline.py` — 需要 ANSYS 测试
- `fea_models.py` — 数据模型扩展推迟（避免破坏 API）
- `apdl_templates.py` — 需要 ANSYS 测试

---

## 2. 核心设计

### 2.1 `topology/cae_bridge.py`

```python
def resolve_named_set_to_faces(
    named_set: NamedTopologySet,
    registry: TopologyRegistry,
) -> CaeResolvedSet:
    """将 NamedTopologySet 解析为具体的面几何信息。
    
    返回：
      - resolved_face_indices: 当前 B-Rep 中匹配的面索引列表
      - resolution_quality: exact | set | ambiguous
      - gate_result: pass | fail | warn
    """

def cae_preflight_gate(
    named_sets: list[NamedTopologySet],
    registry: TopologyRegistry,
) -> CaePreflightResult:
    """CAE 求解前门控检查。
    
    Fail 条件:
      - 任何 NamedTopologySet 中有 unresolved/deleted ID
      - 任何 high-stakes set (load/constraint/contact) 中有 ambiguous ID
      - resolution_quality 低于 consumer_policy 要求
    
    Pass 条件:
      - 所有 ID 解析为 exact 或 deterministic_semantic
      - cardinality 匹配
    """

class CaeResolvedSet(BaseModel):
    name: str
    persistent_ids: list[str]
    resolution_quality: str
    resolved_face_count: int
    gate_result: Literal["pass", "fail", "warn"]
    issues: list[dict]

class CaePreflightResult(BaseModel):
    ok: bool
    resolved_sets: list[CaeResolvedSet]
    blocked_sets: list[dict]
    summary: str
```

### 2.2 集成点

```python
# 使用方式（在 fea_pipeline.py 中，有 ANSYS 时启用）:
from seekflow_engineering_tools.generative_cad.topology.cae_bridge import (
    cae_preflight_gate, resolve_named_set_to_faces,
)

# 从 topology sidecar 恢复 registry
registry = TopologyRegistry()
read_topology_sidecar(sidecar_path, registry)

# 构建 named sets（替代 RegionDef）
load_face = NamedTopologySet(
    name="disk.rim.outer_face",
    persistent_ids=[...],
    semantic_purpose="load",
)
constraint_face = NamedTopologySet(
    name="disk.bore.wall",
    persistent_ids=[...],
    semantic_purpose="constraint",
)

# Preflight gate
gate_result = cae_preflight_gate([load_face, constraint_face], registry)
if not gate_result.ok:
    raise RuntimeError(f"CAE preflight failed: {gate_result.summary}")
```

---

## 3. 实施顺序

```
6.1: topology/cae_bridge.py — resolve + preflight gate + models
6.2: topology/policies.py — CAE policy enforcement hook
6.3: topology/__init__.py — 导出
6.4: 运行全部测试确保零回归
6.5: 写入 Phase 6 测试
```

## 4. 验收标准

- [ ] `resolve_named_set_to_faces()` 通过 TopologyRegistry 解析 NamedTopologySet
- [ ] `cae_preflight_gate()` 阻止 unresolved/deleted/ambiguous 的高风险 set
- [ ] CAE contact face 要求 EXACT_KERNEL_HISTORY
- [ ] 88 已有测试零回归
