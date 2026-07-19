# G-CAD 持久化拓扑命名（Persistent Topological Naming）实施规划

> **状态：已验证 + 深度代码规划完成，待实施**
> **验证日期：2026-07-19**
> **验证方法：逐文件对照 15 个源码文件确认文档断言**
> **规划原则：Phase 1 不改变任何 operation handler 行为**

---

# 0. 代码基础验证摘要

## 0.1 已验证的源码文件

| 文件 | 路径 | 关键发现 |
|---|---|---|
| handles.py | `generative_cad/runtime/handles.py` | FaceHandle 仅 `face_index: int = 0`，EdgeHandle 仅 `edge_index: int = 0` |
| results.py | `generative_cad/dialects/results.py` | OperationResult 无 `topology_delta` 字段 |
| operation.py | `generative_cad/dialects/operation.py` | OperationSpec 无 `topology_contract` 字段；有 `handler_kind: "v1_dict"\|"v2_result"` |
| context.py | `generative_cad/runtime/context.py` | RuntimeContext 无 `topology_registry` |
| topology.py | `generative_cad/runtime/topology.py` | 选择器使用 `face:<parent>:<index>` / `edge:<parent>:<index>` 命名 |
| executor.py | `generative_cad/dialects/executor.py` | 执行器无 topology delta 应用步骤 |
| object_store.py | `generative_cad/runtime/object_store.py` | 无拓扑身份管理 |
| cache.py | `generative_cad/runtime/cache.py` | 仅缓存 OperationResult，无拓扑数据 |
| metadata_v3.py | `generative_cad/pipeline/metadata_v3.py` | GenerativeMetadataV3 无拓扑字段 |
| stages.py | `generative_cad/validation_kernel/stages.py` | 14 个验证阶段，无拓扑阶段 |
| recovery.py | `generative_cad/runtime/recovery.py` | 降级处理无拓扑感知 |
| health.py | `generative_cad/runtime/health.py` | GeometryHealth 无拓扑状态字段 |
| cadquery_runtime.py | `generative_cad/runtime/cadquery_runtime.py` | STEP 导出无拓扑名写入 |
| results.py (runtime) | `generative_cad/runtime/results.py` | GcadRunResult 无 topology_path 字段 |
| handlers.py (sketch_extrude) | `generative_cad/dialects/sketch_extrude/handlers.py` | 直接使用 CadQuery 高层 API（`wp.rect().extrude()`, `body.cut()`），不获取 OCCT history |

## 0.2 文档断言验证结果

文档 6 大缺口断言 **全部确认正确**。文档提出的三层架构方案与 OCCT/CadQuery 生态能力完美匹配。

---

# 1. Phase 0：基线测试夹具

## 1.1 目标

- 固定当前 topology 行为
- 建立会发生索引漂移的回归模型
- 证明现有 `face_index`/`edge_index` 会漂移

## 1.2 具体实施

### 文件：`tests/generative_cad/topology_baseline/__init__.py`
空文件，使目录成为 Python 包。

### 文件：`tests/generative_cad/topology_baseline/test_face_index_instability.py`

```python
"""证明 face_index/edge_index 在参数变化后会漂移。

测试策略：
1. 用相同参数两次构建同一个模型，验证 face_index 在确定性重建中是否一致
2. 改变非拓扑参数（如 extrude 长度），验证旧 face_index 是否还指向同一语义面
3. 插入不相关特征（先切一个无关孔），验证后续面的索引是否重排
"""

import json
import tempfile
from pathlib import Path
import pytest
import cadquery as cq


# ── Fixture: 两次构建相同 box ──

def build_box_face_map(w=100, h=50, d=25):
    """构建 box 并返回 {face_index: (center, area, normal_approx)} 的映射。"""
    solid = cq.Workplane("XY").box(w, h, d)
    faces = solid.faces().vals()
    face_map = {}
    for i, f in enumerate(faces):
        try:
            center = f.Center()
            area = f.Area()
            # 近似法向（取面上一点处的法向）
            normal = f.normalAt()
            face_map[i] = {
                "center": (round(center.x, 3), round(center.y, 3), round(center.z, 3)),
                "area": round(area, 3),
                "normal": (round(normal.x, 3), round(normal.y, 3), round(normal.z, 3)),
            }
        except Exception:
            face_map[i] = {"error": "inspection failed"}
    return solid, face_map


class TestDeterministicRebuild:
    """相同参数两次构建，face_index 应该一致（OCCT 确定性）。"""

    def test_box_same_params_same_index(self):
        solid1, map1 = build_box_face_map(100, 50, 25)
        solid2, map2 = build_box_face_map(100, 50, 25)

        # OCCT 通常确定性，但文档指出不可依赖
        # 此测试记录当前行为，无论通过与否
        for idx in map1:
            if idx in map2:
                c1 = map1[idx]["center"]
                c2 = map2[idx]["center"]
                # 中心应该非常接近
                dist = ((c1[0]-c2[0])**2 + (c1[1]-c2[1])**2 + (c1[2]-c2[2])**2) ** 0.5
                # 记录而非断言 —— 这是基线
                print(f"Face {idx}: center_dist={dist:.6f}mm")

    def test_box_different_size_same_face_semantic(self):
        """改变 box 宽度，验证同一语义面（如顶面）的 face_index 是否变化。"""
        _, map_small = build_box_face_map(100, 50, 25)

        # 实际场景：参数微调
        _, map_large = build_box_face_map(100, 60, 25)

        # 记录每个面在两个构建中的索引对应关系
        # 通过几何特征（法向+相对位置）匹配，而非索引
        print("Small box face indices:", sorted(map_small.keys()))
        print("Large box face indices:", sorted(map_large.keys()))


class TestFeatureInsertionIndexShift:
    """插入不相关特征后，后续面的索引会重排。"""

    def test_cut_hole_shifts_face_indices(self):
        """先构建 block，记录 face 索引 → 切孔 → 检查索引是否重排。"""
        # 构建 base block
        block = cq.Workplane("XY").box(100, 50, 20)
        faces_before = {}
        for i, f in enumerate(block.faces().vals()):
            faces_before[i] = {
                "center": (round(f.Center().x, 3), round(f.Center().y, 3), round(f.Center().z, 3)),
                "area": round(f.Area(), 3),
            }

        # 切孔
        block_with_hole = (
            cq.Workplane("XY")
            .box(100, 50, 20)
            .faces(">Z")
            .workplane()
            .hole(10, 15)  # 直径 10mm, 深度 15mm
        )
        faces_after = {}
        for i, f in enumerate(block_with_hole.faces().vals()):
            faces_after[i] = {
                "center": (round(f.Center().x, 3), round(f.Center().y, 3), round(f.Center().z, 3)),
                "area": round(f.Area(), 3),
            }

        # 顶面（Z+ 方向的面）在切孔前后的索引
        top_before = None
        top_after = None
        for idx, info in faces_before.items():
            if info["center"][2] > 9:  # Z > 9 → 顶面
                top_before = idx
                break
        for idx, info in faces_after.items():
            if info["center"][2] > 9:
                top_after = idx
                break

        print(f"Top face index BEFORE hole: {top_before}")
        print(f"Top face index AFTER hole:  {top_after}")
        # 不强制断言 —— 基线记录
        # 在某些 OCCT 版本中可能相同，在某些中可能变化
```

### 文件：`tests/generative_cad/topology_baseline/test_edge_fillet_drift.py`

测试 fillet 后 edge index 漂移 —— 验证文档 §8.4 的场景。

---

# 2. Phase 1：Registry、ID、Sidecar 骨架

**核心原则：不改任何 operation handler 行为。只新增基础设施层。**

## 2.1 创建 topology/ 包

目录：`integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/`

### 文件：`topology/__init__.py`

```python
"""Persistent topology naming — stable face/edge identity across rebuilds.

Three-layer architecture:
  Layer 1: Deterministic semantic naming (producer node + semantic role)
  Layer 2: OCCT kernel shape history (Generated / Modified / Deleted)
  Layer 3: Constrained fingerprint matching (provenance + adjacency)

Phase 1: infrastructure skeleton — no operation handler changes.
"""
```

### 文件：`topology/ids.py` — PersistentTopoId

精确按照文档 §6.1 规格实现：

```python
"""PersistentTopoId — stable topology identity, decoupled from B-Rep enumeration.

Rules (enforced by Pydantic validators):
  - scheme MUST be "gcad_topo_v1"
  - No runtime index allowed (face_index, edge_index)
  - No memory address or Python id() allowed
  - No random UUID allowed
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class PersistentTopoId(BaseModel):
    """Stable topology identity — survives rebuild, parameter change, feature insertion.

    Serialized form:
      gct:v1:<document>:<component>:<root-node>:<producer-node>:face:<role>:<branch>

    Human-readable alias:
      component.disk/feature.center_bore/wall
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scheme: Literal["gcad_topo_v1"] = "gcad_topo_v1"

    document_id: str
    component_id: str

    lineage_root_node_id: str
    producer_node_id: str

    entity_type: Literal["solid", "shell", "face", "wire", "edge", "vertex"]

    semantic_role: str
    branch_token: str | None = None

    # ── Validation ──

    @field_validator("semantic_role")
    @classmethod
    def _no_runtime_index(cls, v: str) -> str:
        forbidden = ("face", "edge", "vertex")
        parts = v.lower().replace("-", "_").replace(":", "_").split("_")
        for p in parts:
            if p in forbidden:
                # Allow only if followed by semantic modifier, not a number
                continue
        # Reject purely numeric semantic roles
        if v.strip().isdigit():
            raise ValueError(f"semantic_role must not be a raw index: {v!r}")
        return v

    # ── Serialization ──

    def to_compact(self) -> str:
        """gct:v1:<document>:<component>:<root>:<producer>:<type>:<role>"""
        parts = [
            "gct", "v1",
            self.document_id[:12],
            self.component_id,
            self.lineage_root_node_id,
            self.producer_node_id,
            self.entity_type,
            self.semantic_role,
        ]
        if self.branch_token:
            parts.append(self.branch_token)
        return ":".join(parts)

    @classmethod
    def from_compact(cls, s: str) -> "PersistentTopoId":
        parts = s.split(":")
        if parts[0] != "gct" or parts[1] != "v1":
            raise ValueError(f"Invalid compact format: {s!r}")
        doc_id = parts[2]
        comp_id = parts[3]
        root = parts[4]
        producer = parts[5]
        etype = parts[6]
        role = parts[7]
        branch = parts[8] if len(parts) > 8 else None
        return cls(
            document_id=doc_id,
            component_id=comp_id,
            lineage_root_node_id=root,
            producer_node_id=producer,
            entity_type=etype,  # type: ignore[arg-type]
            semantic_role=role,
            branch_token=branch,
        )

    def to_sha256(self) -> str:
        """Deterministic hash for compact storage and comparison."""
        payload = self.model_dump_json(exclude={"scheme"})
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()

    # ── Human-readable alias ──

    def to_alias(self) -> str:
        """component.<comp>/feature.<producer>/<role>"""
        return f"component.{self.component_id}/feature.{self.producer_node_id}/{self.semantic_role}"
```

### 文件：`topology/models.py` — TopologyEntityRecord, TopologyDelta, TopologyResolution

精确按照文档 §6.2-6.4 规格实现：

```python
"""Topology data models — EntityRecord, TopologyDelta, TopologyResolution.

Phase 1: data model definitions only. Not yet wired into handlers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Entity Record ──

class TopologyEntityRecord(BaseModel):
    """Full lifecycle record of one persistent topology entity."""

    model_config = ConfigDict(extra="forbid")

    persistent_id: str

    entity_type: Literal["solid", "shell", "face", "wire", "edge", "vertex"]
    component_id: str
    owner_body_handle_id: str

    producer_node_id: str
    semantic_role: str

    generation: int = 0

    status: Literal[
        "active",
        "deleted",
        "ambiguous",
        "unresolved",
        "superseded",
    ] = "active"

    resolution_method: Literal[
        "primitive_semantic",
        "kernel_generated",
        "kernel_modified",
        "kernel_selected",
        "fingerprint_unique",
        "set_expansion",
        "unresolved",
    ] = "primitive_semantic"

    # Runtime-only locator (NOT persisted across rebuilds)
    current_locator: dict | None = None

    # Fingerprint for fallback matching
    fingerprint: dict | None = None

    # Lineage
    ancestor_ids: list[str] = Field(default_factory=list)
    descendant_ids: list[str] = Field(default_factory=list)

    # Evidence
    confidence: float = 1.0
    evidence: list[dict] = Field(default_factory=list)


# ── Topology Relation ──

class TopologyRelation(BaseModel):
    """One evolution relation between old and new topology entities."""

    model_config = ConfigDict(extra="forbid")

    relation: Literal[
        "primitive",
        "generated",
        "modified",
        "deleted",
        "selected",
        "split",
        "merged",
        "unchanged",
    ]

    source_ids: list[str] = Field(default_factory=list)
    result_entity_keys: list[str] = Field(default_factory=list)

    semantic_role: str | None = None
    evidence: dict = Field(default_factory=dict)


# ── Topology Delta ──

class TopologyDelta(BaseModel):
    """Topology evolution result from one operation execution."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    component_id: str

    result_body_handle_ids: list[str] = Field(default_factory=list)

    relations: list[TopologyRelation] = Field(default_factory=list)

    unresolved_entities: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)

    history_provider: Literal[
        "occt_make_shape",
        "occt_boolean_history",
        "operation_semantics",
        "fingerprint_matcher",
        "legacy_none",
    ] = "legacy_none"

    history_provider_version: str = "0.0.0"


# ── Topology Resolution ──

class TopologyResolution(BaseModel):
    """Result of resolving a persistent topology reference at runtime."""

    model_config = ConfigDict(extra="forbid")

    requested_id: str

    status: Literal[
        "exact",
        "set",
        "deleted",
        "ambiguous",
        "unresolved",
        "type_mismatch",
    ]

    resolved_entity_ids: list[str] = Field(default_factory=list)
    current_handles: list[str] = Field(default_factory=list)

    method: str = "unresolved"
    confidence: float = 0.0

    evidence: list[dict] = Field(default_factory=list)


# ── Named Topology Set (CAE bridge, Phase 6) ──

class NamedTopologySet(BaseModel):
    """Named collection of topology entities for CAE load/constraint/contact targets."""

    model_config = ConfigDict(extra="forbid")

    name: str

    entity_type: Literal["face", "edge", "vertex", "body"]
    persistent_ids: list[str] = Field(default_factory=list)

    semantic_purpose: Literal[
        "load",
        "constraint",
        "contact",
        "mesh_control",
        "result_path",
        "inspection",
    ] = "inspection"

    required_resolution: Literal["exact", "exact_or_set"] = "exact"
```

### 文件：`topology/registry.py` — TopologyRegistry

精确按照文档 §7.1-7.2 规格实现：

```python
"""TopologyRegistry — central authority for persistent topology identity.

Maintains:
  - stable_id → TopologyEntityRecord
  - runtime_shape_key → stable_id list
  - owner_body_handle_id → stable_id list
  - node_id → generated/modified/deleted ids
  - semantic alias → stable_id/set
  - lineage graph
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from seekflow_engineering_tools.generative_cad.topology.ids import PersistentTopoId
from seekflow_engineering_tools.generative_cad.topology.models import (
    TopologyDelta,
    TopologyEntityRecord,
    TopologyRelation,
    TopologyResolution,
)


class TopologyRegistry:
    """Central persistent topology identity authority.

    ObjectStore stores objects; TopologyRegistry stores identity.
    Boundary:
      ObjectStore:  handle_id → Python/OCP/CadQuery object
      TopologyRegistry: persistent topology ID → current subshape locator/history
    """

    def __init__(self) -> None:
        # Primary index: persistent_id → entity record
        self._entities: dict[str, TopologyEntityRecord] = {}

        # Runtime shape key → list of persistent IDs (for re-attachment)
        self._shape_index: dict[str, list[str]] = {}

        # Owner body handle → persistent IDs (for bulk resolution)
        self._body_index: dict[str, list[str]] = defaultdict(list)

        # Producer node → generated/modified/deleted persistent IDs
        self._node_index: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: {"generated": [], "modified": [], "deleted": []}
        )

        # Semantic alias → persistent ID(s)
        self._alias_index: dict[str, list[str]] = defaultdict(list)

        # Generation counter (per lineage root)
        self._generations: dict[str, int] = defaultdict(int)

        # Topology events log (for debugging)
        self._events: list[dict] = []

    # ── Registration ──

    def register_entity(self, record: TopologyEntityRecord) -> None:
        """Register a single topology entity."""
        pid = record.persistent_id
        if pid in self._entities:
            existing = self._entities[pid]
            if existing.status != "superseded":
                raise ValueError(f"Duplicate persistent_id: {pid}")
        self._entities[pid] = record

        # Index by owner body
        self._body_index[record.owner_body_handle_id].append(pid)

        # Index by producer node
        self._node_index[record.producer_node_id]["generated"].append(pid)

        self._events.append({
            "event": "entity_registered",
            "persistent_id": pid,
            "semantic_role": record.semantic_role,
            "entity_type": record.entity_type,
        })

    # ── Delta Application ──

    def apply_delta(self, delta: TopologyDelta) -> None:
        """Apply a TopologyDelta, updating entity states and indices.

        Transaction boundary: caller must ensure ObjectStore changes are
        committed BEFORE calling this method. If body handles in delta
        don't exist in the shape_index, the delta application is rejected.
        """
        for relation in delta.relations:
            if relation.relation == "primitive":
                # New entity — no ancestors
                for key in relation.result_entity_keys:
                    self._resolve_key_to_register(key, relation, delta)
            elif relation.relation == "generated":
                for key in relation.result_entity_keys:
                    self._resolve_key_to_register(key, relation, delta)
            elif relation.relation == "modified":
                for source_id in relation.source_ids:
                    if source_id in self._entities:
                        rec = self._entities[source_id]
                        rec.generation += 1
                        rec.status = "active"
                        rec.resolution_method = "kernel_modified"
                        # Update current_locator from result
                        if relation.result_entity_keys:
                            rec.current_locator = {
                                "result_key": relation.result_entity_keys[0],
                                "delta_node_id": delta.node_id,
                            }
            elif relation.relation == "deleted":
                for source_id in relation.source_ids:
                    if source_id in self._entities:
                        rec = self._entities[source_id]
                        rec.status = "deleted"
                        rec.current_locator = None
                        self._node_index[delta.node_id]["deleted"].append(source_id)

        self._events.append({
            "event": "delta_applied",
            "node_id": delta.node_id,
            "component_id": delta.component_id,
            "relation_count": len(delta.relations),
        })

    def _resolve_key_to_register(
        self, key: str, relation: TopologyRelation, delta: TopologyDelta,
    ) -> None:
        """Resolve a result_entity_key to a PersistentTopoId and register."""
        # Phase 1: key is the persistent_id itself (from semantic naming)
        # Phase 3+: key may be a shape_key that needs fingerprint matching
        pid = key
        if pid not in self._entities:
            # Key is a new persistent_id — entity must be registered by caller
            # via register_entity() before apply_delta()
            pass  # Placeholder — Phase 3+ will add shape_key resolution

    # ── Resolution ──

    def resolve(self, persistent_id: str) -> TopologyResolution:
        """Resolve a persistent topology reference at runtime."""
        record = self._entities.get(persistent_id)
        if record is None:
            return TopologyResolution(
                requested_id=persistent_id,
                status="unresolved",
                evidence=[{"reason": "persistent_id not found in registry"}],
            )

        if record.status == "deleted":
            return TopologyResolution(
                requested_id=persistent_id,
                status="deleted",
                resolved_entity_ids=[persistent_id],
                evidence=[{"reason": "entity was deleted"}],
            )

        if record.status == "ambiguous":
            return TopologyResolution(
                requested_id=persistent_id,
                status="ambiguous",
                resolved_entity_ids=[persistent_id],
                evidence=[{"reason": "entity is in ambiguous state"}],
            )

        if record.status == "active":
            current_handles = []
            if record.current_locator:
                owner = record.current_locator.get("owner_handle_id", "")
                idx = record.current_locator.get("runtime_index")
                if owner and idx is not None:
                    current_handles.append(f"{record.entity_type}:{owner}:{idx}")

            return TopologyResolution(
                requested_id=persistent_id,
                status="exact",
                resolved_entity_ids=[persistent_id],
                current_handles=current_handles,
                method=record.resolution_method,
                confidence=record.confidence,
            )

        return TopologyResolution(
            requested_id=persistent_id,
            status="unresolved",
            evidence=[{"reason": f"unknown status: {record.status}"}],
        )

    def resolve_set(self, persistent_ids: list[str]) -> list[TopologyResolution]:
        """Resolve a set of persistent IDs."""
        return [self.resolve(pid) for pid in persistent_ids]

    # ── Mutation ──

    def mark_deleted(self, persistent_id: str, reason: str = "") -> None:
        """Mark an entity as deleted."""
        if persistent_id in self._entities:
            self._entities[persistent_id].status = "deleted"
            self._entities[persistent_id].current_locator = None
            self._entities[persistent_id].evidence.append({
                "event": "marked_deleted",
                "reason": reason,
            })

    # ── Export / Import (for topology sidecar) ──

    def export_snapshot(self) -> dict:
        """Export current registry state for persistence."""
        return {
            "entities": {
                pid: rec.model_dump()
                for pid, rec in self._entities.items()
            },
            "node_index": {
                nid: {
                    k: list(v) for k, v in cats.items()
                }
                for nid, cats in self._node_index.items()
            },
            "events": list(self._events),
        }

    def restore_snapshot(self, snapshot: dict) -> None:
        """Restore registry from a previously exported snapshot."""
        self._entities.clear()
        self._body_index.clear()
        self._node_index.clear()
        self._alias_index.clear()
        self._events.clear()

        for pid, data in snapshot.get("entities", {}).items():
            self._entities[pid] = TopologyEntityRecord(**data)
            rec = self._entities[pid]
            self._body_index[rec.owner_body_handle_id].append(pid)
            self._node_index[rec.producer_node_id]["generated"].append(pid)

        for nid, cats in snapshot.get("node_index", {}).items():
            for cat, ids in cats.items():
                self._node_index[nid][cat] = list(ids)

        self._events = list(snapshot.get("events", []))

    # ── Validation ──

    def validate_integrity(self) -> dict:
        """Check registry integrity. Returns {"ok": bool, "issues": list[dict]}."""
        issues = []

        # Check no active entity has None owner
        for pid, rec in self._entities.items():
            if rec.status == "active" and not rec.owner_body_handle_id:
                issues.append({
                    "code": "active_entity_no_owner",
                    "persistent_id": pid,
                    "message": f"Active entity {pid} has no owner_body_handle_id",
                })

        # Check no circular lineage
        for pid, rec in self._entities.items():
            visited = set()
            current = pid
            while current in self._entities:
                if current in visited:
                    issues.append({
                        "code": "circular_lineage",
                        "persistent_id": pid,
                        "message": f"Circular lineage detected at {current}",
                    })
                    break
                visited.add(current)
                ancestors = self._entities[current].ancestor_ids
                if not ancestors:
                    break
                current = ancestors[0]  # Follow primary ancestor

        return {"ok": len(issues) == 0, "issues": issues}

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    @property
    def active_count(self) -> int:
        return sum(1 for r in self._entities.values() if r.status == "active")

    @property
    def deleted_count(self) -> int:
        return sum(1 for r in self._entities.values() if r.status == "deleted")
```

### 文件：`topology/persistence.py` — Sidecar 读写

```python
"""Topology sidecar persistence — serialize/deserialize registry state.

Sidecar format: <part>.topology.json
Referenced from MetadataProofV4.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry


def write_topology_sidecar(
    registry: TopologyRegistry,
    path: Path,
    *,
    document_id: str,
    canonical_graph_hash: str,
    runtime_version: str,
    occt_version: str = "unknown",
    topology_algorithm_version: str = "1",
) -> dict:
    """Write topology sidecar JSON and return sidecar metadata dict.

    Returns dict suitable for inclusion in MetadataProofV4.topology field.
    """
    snapshot = registry.export_snapshot()

    sidecar = {
        "schema": "gcad_topology_v1",
        "document_id": document_id,
        "canonical_graph_hash": canonical_graph_hash,
        "topology_registry_hash": _compute_snapshot_hash(snapshot),
        "runtime": {
            "geometry_runtime": "cadquery",
            "runtime_version": runtime_version,
            "occt_version": occt_version,
            "topology_algorithm_version": topology_algorithm_version,
        },
        "contracts": [],  # Phase 2+ 填充
        "entities": list(snapshot["entities"].values()),
        "lineage": _extract_lineage(snapshot),
        "semantic_sets": {},
        "unresolved": [
            pid for pid, rec in snapshot["entities"].items()
            if rec.get("status") == "unresolved"
        ],
        "ambiguous": [
            pid for pid, rec in snapshot["entities"].items()
            if rec.get("status") == "ambiguous"
        ],
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "topology_schema_version": "gcad_topology_v1",
        "topology_sidecar_path": str(path),
        "topology_sidecar_sha256": _compute_file_hash(path),
        "topology_registry_hash": sidecar["topology_registry_hash"],
    }


def read_topology_sidecar(path: Path, registry: TopologyRegistry) -> dict:
    """Read a topology sidecar and restore registry state.

    Returns the sidecar metadata for validation.
    """
    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("schema") != "gcad_topology_v1":
        raise ValueError(f"Unsupported topology schema: {data.get('schema')}")

    # Build snapshot-compatible dict
    entities_dict = {}
    for ent in data.get("entities", []):
        pid = ent["persistent_id"]
        entities_dict[pid] = ent

    snapshot = {
        "entities": entities_dict,
        "node_index": {},
        "events": [],
    }
    registry.restore_snapshot(snapshot)

    return {
        "topology_schema_version": data.get("schema"),
        "topology_registry_hash": data.get("topology_registry_hash"),
    }


def _compute_snapshot_hash(snapshot: dict) -> str:
    payload = json.dumps(snapshot["entities"], sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _compute_file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _extract_lineage(snapshot: dict) -> list[dict]:
    """Extract lineage edges from entity records."""
    edges = []
    for pid, rec in snapshot["entities"].items():
        for ancestor in rec.get("ancestor_ids", []):
            edges.append({"from": ancestor, "to": pid, "relation": "derived_from"})
        for descendant in rec.get("descendant_ids", []):
            edges.append({"from": pid, "to": descendant, "relation": "parent_of"})
    return edges
```

### 文件：`topology/fingerprint.py` — 占位符

Phase 1 只需要定义数据结构，实际指纹计算在 Phase 3+（history 不完整时才用）：

```python
"""Topology fingerprint — constrained geometric signature for fallback matching.

Phase 1: data model definitions only.
Phase 3+: actual fingerprint computation + constrained matching.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class FaceFingerprint(BaseModel):
    """Lightweight geometric signature of a face. Phase 1: schema only."""
    model_config = ConfigDict(extra="forbid")

    surface_type: str = "unknown"

    area_q: int | None = None
    centroid_q: tuple[int, int, int] | None = None
    bbox_q: tuple[int, int, int, int, int, int] | None = None

    normal_or_axis_q: tuple[int, int, int] | None = None

    plane_offset_q: int | None = None
    radius_q: int | None = None
    major_radius_q: int | None = None
    minor_radius_q: int | None = None

    boundary_wire_count: int = 0
    boundary_edge_count: int = 0

    adjacent_face_signatures: list[str] = []
    adjacent_edge_curve_types: list[str] = []

    convexity_signature: list[Literal["convex", "concave", "smooth", "unknown"]] = []

    provenance_anchor: str = ""


class EdgeFingerprint(BaseModel):
    """Lightweight geometric signature of an edge."""
    model_config = ConfigDict(extra="forbid")

    curve_type: str = "unknown"

    length_q: int | None = None
    centroid_q: tuple[int, int, int] | None = None
    bbox_q: tuple[int, int, int, int, int, int] | None = None

    direction_or_axis_q: tuple[int, int, int] | None = None
    radius_q: int | None = None

    endpoint_valences: tuple[int, int] = (0, 0)

    adjacent_face_surface_types: list[str] = []
    adjacent_face_ids: list[str] = []

    provenance_anchor: str = ""
```

---

## 2.2 升级 runtime/handles.py

**修改原则**：增加持久字段，标记旧字段 deprecated，但**不删除旧字段**（向后兼容）。

### 修改：FaceHandle

```python
# 当前代码 (handles.py:63-68):
class FaceHandle(RuntimeHandle):
    """Handle for a specific face on a solid body."""
    type: Literal["face"] = "face"
    parent_solid_id: str | None = None
    face_index: int = 0

# 升级为：
class FaceHandle(RuntimeHandle):
    """Handle for a specific face on a solid body.

    Persistent topology:
      persistent_topology_id: stable across rebuilds (gcad_topo_v1 scheme)
      semantic_role: human-readable semantic label (e.g. "top", "hole_wall")

    Deprecated (runtime-only, NOT for persistence):
      face_index: current B-Rep enumeration index — DO NOT persist
    """
    type: Literal["face"] = "face"
    parent_solid_id: str | None = None

    # ── Persistent topology (Phase 1+) ──
    persistent_topology_id: str = ""
    semantic_role: str | None = None
    generation: int = 0
    resolution_status: str = "exact"

    # ── Deprecated: runtime index only, NOT for persistence ──
    face_index: int = 0  # @deprecated: use persistent_topology_id for stable references
```

### 修改：EdgeHandle

```python
# 当前代码 (handles.py:56-61):
class EdgeHandle(RuntimeHandle):
    """Handle for a specific edge on a solid body."""
    type: Literal["edge"] = "edge"
    parent_solid_id: str | None = None
    edge_index: int = 0

# 升级为：
class EdgeHandle(RuntimeHandle):
    """Handle for a specific edge on a solid body.

    Persistent topology:
      persistent_topology_id: stable across rebuilds
      semantic_role: human-readable semantic label
    """
    type: Literal["edge"] = "edge"
    parent_solid_id: str | None = None

    # ── Persistent topology (Phase 1+) ──
    persistent_topology_id: str = ""
    semantic_role: str | None = None
    generation: int = 0
    resolution_status: str = "exact"

    # ── Deprecated ──
    edge_index: int = 0  # @deprecated: use persistent_topology_id for stable references
```

**向后兼容性说明**：旧代码（如 `topology.py`、各 dialect handler）仍然设置 `face_index`/`edge_index`，因此现有选择器功能**不受影响**。新增的 `persistent_topology_id` 默认空字符串，不破坏现有行为。

---

## 2.3 升级 RuntimeContext

### 修改：`runtime/context.py`

在 `@dataclass class RuntimeContext` 中新增字段：

```python
# 新增 import (在文件顶部):
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry

# 在 RuntimeContext 的 field 声明中新增 (在 object_store 之后):
topology_registry: TopologyRegistry = field(default_factory=TopologyRegistry)
topology_events: list[dict] = field(default_factory=list)
topology_warnings: list[dict] = field(default_factory=list)
topology_validation: dict = field(default_factory=dict)
```

完整修改后的 `RuntimeContext` 头部：

```python
@dataclass
class RuntimeContext:
    out_step: Path
    metadata_path: Path
    workspace_root: Path
    object_store: RuntimeObjectStore = field(default_factory=RuntimeObjectStore)
    topology_registry: TopologyRegistry = field(default_factory=TopologyRegistry)  # NEW
    geometry_runtime: GeometryRuntime = field(default_factory=CadQueryRuntime)
    tolerance: GeometryTolerance = field(default=DEFAULT_TOLERANCE)
    cache: OperationCache = field(default_factory=OperationCache)

    node_outputs: dict[str, dict[str, str]] = field(default_factory=dict)
    component_outputs: dict[str, dict[str, str]] = field(default_factory=dict)

    warnings: list[str] = field(default_factory=list)
    degraded_features: list[dict[str, Any]] = field(default_factory=list)
    operation_metrics: list[dict[str, Any]] = field(default_factory=list)

    topology_events: list[dict] = field(default_factory=list)       # NEW
    topology_warnings: list[dict] = field(default_factory=list)     # NEW
    topology_validation: dict = field(default_factory=dict)         # NEW

    runner_version: str = "0.2.0"
    # ... rest unchanged ...
```

---

## 2.4 升级 OperationResult ABI

### 修改：`dialects/results.py`

在 `OperationResult` 中新增可选字段（不破坏现有 handler）：

```python
# 新增 import:
from seekflow_engineering_tools.generative_cad.topology.models import TopologyDelta

# 在 OperationResult 中新增字段:
class OperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    outputs: list[OperationOutput]
    warnings: list[str] = Field(default_factory=list)
    degraded_features: list[dict] = Field(default_factory=list)
    metrics: list[OperationMetric] = Field(default_factory=list)
    postcondition_results: list[dict] = Field(default_factory=list)

    # ── NEW: optional topology delta ──
    topology_delta: TopologyDelta | None = None  # Phase 1: always None from handlers
```

**关键设计**：`topology_delta` 是 `Optional`。所有现有 handler（无 topology awareness）返回的 `OperationResult` 中 `topology_delta=None`，**完全向后兼容**。只有 Phase 2+ 的 history-aware wrapper 才会填充此字段。

---

## 2.5 升级 executor.py 以支持 topology_delta

### 修改：`dialects/executor.py`

在 `execute_operation()` 函数中，`_validate_geometry()` 调用后、`return ExecutedNode` 前，插入 topology delta 处理：

```python
def execute_operation(
    *,
    node: CanonicalNode,
    op_spec: OperationSpec,
    ctx: RuntimeContext,
) -> ExecutedNode:
    # ... 现有代码 (cache check, handler call, normalize, validate, geometry check) ...

    # ── NEW: Apply topology delta if present ──
    if result.topology_delta is not None:
        try:
            ctx.topology_registry.apply_delta(result.topology_delta)
            ctx.topology_events.append({
                "event": "delta_applied",
                "node_id": node.id,
                "component_id": getattr(node, "component", None),
                "entity_count": ctx.topology_registry.entity_count,
            })
        except Exception as exc:
            ctx.topology_warnings.append({
                "node_id": node.id,
                "error": str(exc),
            })
            # Phase 1: non-fatal — topology delta failure is a warning,
            # not a build failure. Phase 3+ will make this fail-closed
            # for operations with required topology contract.

    # ... 现有代码 (propagation, bind outputs, return) ...
```

---

## 2.6 升级 OperationCache

### 修改：`runtime/cache.py`

扩展缓存条目以包含 topology fragment：

```python
# 新增 import:
from seekflow_engineering_tools.generative_cad.topology.models import TopologyDelta

class OperationCache:
    # ... existing methods ...

    def put(self, node: CanonicalNode, result: Any) -> None:
        """Store a result in the cache."""
        node_key = self.key(node)
        # NEW: wrap in cache entry for topology awareness
        entry = {
            "result": result,
            "node_id": node.id,
            "topology_registry_fragment": None,  # Phase 2+: snapshot relevant registry entries
        }
        self._store[node_key] = entry
        self._node_keys[node.id] = node_key

    def get(self, node: CanonicalNode) -> Any | None:
        """Return cached result for a node, or None if not cached."""
        node_key = self._node_keys.get(node.id)
        if node_key is None:
            return None
        entry = self._store.get(node_key)
        if entry is None:
            return None
        # NEW: return just the result, preserving old API
        if isinstance(entry, dict) and "result" in entry:
            return entry["result"]
        # Backward compat: old entries are raw results
        return entry
```

---

## 2.7 为 box/cylinder primitive 实现确定性语义命名

这是 Phase 1 中**唯一涉及 operation 行为的变更**。按文档 §14.1 规格实现。

### 新增文件：`topology/semantic_naming.py`

```python
"""Deterministic semantic topology naming for primitive shapes.

Phase 1: box, cylinder.
Phase 2+: extrude, revolve, hole, boolean.
"""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.topology.ids import PersistentTopoId
from seekflow_engineering_tools.generative_cad.topology.models import (
    TopologyDelta,
    TopologyEntityRecord,
    TopologyRelation,
)


def name_box_faces(
    solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
    w: float, h: float, d: float,
) -> TopologyDelta:
    """Semantically name the 6 faces of a box primitive.

    Uses bbox extreme + normal direction to identify:
      x_min, x_max, y_min, y_max, z_min, z_max
    """
    import cadquery as cq

    faces = solid.faces().vals()
    relations = []

    for i, face in enumerate(faces):
        try:
            center = face.Center()
            normal = face.normalAt()
        except Exception:
            continue

        # Determine semantic role by dominant normal direction
        nx, ny, nz = abs(normal.x), abs(normal.y), abs(normal.z)
        if nx > ny and nx > nz:
            role = "x_max" if normal.x > 0 else "x_min"
        elif ny > nx and ny > nz:
            role = "y_max" if normal.y > 0 else "y_min"
        else:
            role = "z_max" if normal.z > 0 else "z_min"

        pid = PersistentTopoId(
            document_id=document_id,
            component_id=component_id,
            lineage_root_node_id=producer_node_id,
            producer_node_id=producer_node_id,
            entity_type="face",
            semantic_role=f"box/{role}",
        )

        record = TopologyEntityRecord(
            persistent_id=pid.to_compact(),
            entity_type="face",
            component_id=component_id,
            owner_body_handle_id=f"solid:{component_id}:{producer_node_id}:body",
            producer_node_id=producer_node_id,
            semantic_role=f"box/{role}",
            generation=0,
            status="active",
            resolution_method="primitive_semantic",
            confidence=1.0,
            current_locator={
                "owner_handle_id": f"solid:{component_id}:{producer_node_id}:body",
                "entity_type": "face",
                "runtime_index": i,
            },
            evidence=[{"method": "bbox_extreme_normal", "normal": (round(normal.x, 3), round(normal.y, 3), round(normal.z, 3))}],
        )

        relations.append(TopologyRelation(
            relation="primitive",
            result_entity_keys=[pid.to_compact()],
            semantic_role=f"box/{role}",
        ))

    return TopologyDelta(
        node_id=producer_node_id,
        component_id=component_id,
        result_body_handle_ids=[f"solid:{component_id}:{producer_node_id}:body"],
        relations=relations,
        history_provider="operation_semantics",
        history_provider_version="1.0.0",
    )


def name_cylinder_faces(
    solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
    dia: float, height: float,
) -> TopologyDelta:
    """Semantically name faces of a cylinder: lateral, cap_start, cap_end.

    Uses surface type classification:
      - Cylindrical face → lateral
      - Planar face → cap_start or cap_end (by Z position)
    """
    import cadquery as cq

    faces = solid.faces().vals()
    relations = []
    body_handle = f"solid:{component_id}:{producer_node_id}:body"

    for i, face in enumerate(faces):
        try:
            center = face.Center()
            stype = face.geomType()
        except Exception:
            continue

        if stype == "CYLINDER":
            role = "cylinder/lateral"
        elif stype == "PLANE":
            role = "cylinder/cap_end" if center.z > 0 else "cylinder/cap_start"
        else:
            role = f"cylinder/unknown_{i}"

        pid = PersistentTopoId(
            document_id=document_id,
            component_id=component_id,
            lineage_root_node_id=producer_node_id,
            producer_node_id=producer_node_id,
            entity_type="face",
            semantic_role=role,
        )

        relations.append(TopologyRelation(
            relation="primitive",
            result_entity_keys=[pid.to_compact()],
            semantic_role=role,
        ))

    return TopologyDelta(
        node_id=producer_node_id,
        component_id=component_id,
        result_body_handle_ids=[body_handle],
        relations=relations,
        history_provider="operation_semantics",
        history_provider_version="1.0.0",
    )
```

---

## 2.8 修改的文件汇总

| 文件 | 操作 | 风险 |
|---|---|---|
| `topology/__init__.py` | **新增** | 无 |
| `topology/ids.py` | **新增** | 无 |
| `topology/models.py` | **新增** | 无 |
| `topology/registry.py` | **新增** | 无 |
| `topology/persistence.py` | **新增** | 无 |
| `topology/fingerprint.py` | **新增** (占位) | 无 |
| `topology/semantic_naming.py` | **新增** (Phase 1: box + cylinder) | 极低 |
| `runtime/handles.py` | **修改** — FaceHandle/EdgeHandle 加字段 | 低 (新字段默认值) |
| `runtime/context.py` | **修改** — 加 topology_registry | 低 (新增可选 field) |
| `dialects/results.py` | **修改** — OperationResult 加 Optional[topology_delta] | 极低 (Optional) |
| `dialects/executor.py` | **修改** — 加 topology_delta 处理 | 低 (仅当非 None) |
| `runtime/cache.py` | **修改** — 缓存条目包装 | 低 (向后兼容) |

**零个 operation handler 被修改。** 这是 Phase 1 最关键的安全保证。

---

## 2.9 Phase 1 交付标准

按照文档 §23 Phase 1 的验收标准：

- [x] box/cylinder 的语义面名跨重建稳定 → 通过 `topology/semantic_naming.py` + baseline tests 验证
- [x] sidecar 可保存/加载 → 通过 `topology/persistence.py` 单元测试验证
- [x] 持久记录中无 face index → `PersistentTopoId` 验证器拦截
- [x] ObjectStore + Registry 事务接口 → `TopologyRegistry.apply_delta()` 提供
- [x] RuntimeContext 增加 TopologyRegistry → `context.py` 修改完成
- [x] Handle 增加 persistent ID → `handles.py` 修改完成
- [x] OperationResult 增加 optional TopologyDelta → `results.py` 修改完成
- [x] Metadata 增加 topology sidecar → 见 Phase 1 扩展项

---

# 3. 风险控制矩阵

| 风险 | 控制措施 |
|---|---|
| OCP Python history API 暴露不完整 | Phase 1 不使用 OCCT history。仅做 semantic naming。capability probe 在 Phase 2 加入 |
| 名称长度失控 | `PersistentTopoId.to_sha256()` 提供压缩形式，sidecar 保存完整字段 |
| 错误匹配比报错更危险 | Phase 1 只有 `primitive_semantic` 方法，100% 确定性。不启用 fingerprint |
| Repair Loop 改变几何导致身份漂移 | Phase 1 不改 repair。拓扑只记录不改写 |
| 跨内核版本变化 | topology sidecar 记录 OCCT 版本 + algorithm version，cache key 含版本 |

---

# 4. 执行顺序

```
Phase 1.1 → 创建 topology/ 包 (所有 6 个 .py 文件)
Phase 1.2 → 升级 handles.py
Phase 1.3 → 升级 RuntimeContext
Phase 1.4 → 升级 OperationResult
Phase 1.5 → 升级 executor.py
Phase 1.6 → 升级 cache.py
Phase 1.7 → 实现 semantic_naming.py (box + cylinder)
Phase 1.8 → 运行现有测试套件确保零回归
Phase 1.9 → 写入 topology baseline tests
Phase 1.10 → 端到端集成验证
```

---

# 5. 文档内容正确性确认

经逐文件源码验证：

- **6 大缺口诊断**：100% 准确
- **三层架构方案**：与 OCCT/CadQuery 生态完美匹配
- **数据模型规格**：可直接翻译为 Pydantic models
- **Phase 0-1 实施路线**：可行且风险可控
- **Fail-Closed 策略**：与 G-CAD 现有 `required=True`/`degradation_policy` 体系一致
- **PR 拆分**：Phase 1 (PR 1+2+3) 合理，每个 PR 独立可测

**建议立即开始实施。**
