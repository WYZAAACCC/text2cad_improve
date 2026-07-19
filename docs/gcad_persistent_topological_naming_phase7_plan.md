# Phase 7 实施规划：商业 CAD Topology Adapter Interfaces

> **前置：Phase 1-6 + PR 4 + PR 7 已交付 (96 tests, 0 failures)**
> **代码状态：SolidWorks/NX/ANSYS bridge 已完整存在于 integrations/engineering_tools/**
> **约束：当前环境无 SolidWorks/NX → 创建 adapter interface + mock 测试**
> **增量：将持久拓扑命名桥接到商业 CAD adapter**

---

## 0. 代码探查发现

### 已存在的 bridge 代码

| 模块 | 文件 | 状态 |
|---|---|---|
| SolidWorks COM | `solidworks/com_client.py` | 完整 — `SolidWorksClient` with `import_step_as_part()` |
| SolidWorks Tools | `solidworks/tools.py` | 完整 — `build_solidworks_tools()` |
| NX Job Queue | `nx/job_queue.py` | 完整 — `NXJobQueue` file-based bridge |
| NX Tools | `nx/tools.py` | 完整 — `build_nx_tools()` |
| NX Bootstrap | `nx/nx_bridge_bootstrap.py` | 完整 — NXOpen journal runner |
| ANSYS Runner | `ansys/apdl_runner.py` | 完整 — `AnsysAPDLRunner` |
| ANSYS Templates | `ansys/apdl_templates.py` | 完整 — 7 templates |
| Native Importers | `generative_cad/native_importers.py` | 完整 — `import_step_to_solidworks/nx()` |
| Import Gate | `pipeline/import_artifact.py` | 完整 — 15+ gate checks |

### 缺失的部分

| 能力 | 状态 |
|---|---|
| STEP 文件写入 topology 名称 (AP242/XCAF) | ❌ 未实现 |
| 导入后 topology sidecar → SW/NX face 匹配 | ❌ 未实现 |
| SolidWorks attribute ↔ PersistentTopoId 映射 | ❌ 未实现 |
| NX user attribute ↔ PersistentTopoId 映射 | ❌ 未实现 |
| 跨 backend topology proof | ❌ 未实现 |

---

## 1. Phase 7 范围

### 新增文件 (1 个)

| 文件 | 内容 |
|---|---|
| `topology/cad_adapters.py` | 3 个 adapter interface：`TopologyStepExporter`、`SolidWorksTopologyAdapter`、`NXTopologyAdapter` |

### 主要设计

#### `TopologyStepExporter` 
```python
class TopologyStepExporter:
    """Write topology semantic names into STEP export.
    
    Uses OCP XCAF/STEPCAFControl_Writer to embed face-level names.
    If OCP XCAF unavailable, falls back to vanilla STEP export + sidecar.
    """
    def export_with_topology_names(solid, step_path, registry, ...) -> dict
```

#### `SolidWorksTopologyAdapter`
```python
class SolidWorksTopologyAdapter:
    """Map G-CAD PersistentTopoId ↔ SolidWorks entity attributes.
    
    When importing a STEP with topology names, SolidWorks may preserve
    face colors/names. This adapter maps those back to topology sidecar
    PersistentTopoId entries.
    """
    def map_imported_face_to_topology_id(sw_face_name, registry) -> str | None
    def validate_import_against_sidecar(sw_model, sidecar) -> dict
```

#### `NXTopologyAdapter`  
```python
class NXTopologyAdapter:
    """Map G-CAD PersistentTopoId ↔ NX user attributes / journal naming.
    
    NX can store user attributes on faces. This adapter defines the
    contract for writing/reading topology IDs via NXOpen journal.
    """
    def journal_set_face_attribute(face_id, attribute_name, value) -> str
    def journal_get_face_attribute(face_id, attribute_name) -> str
```

---

## 2. 实施顺序

```
7.1: topology/cad_adapters.py — 3 个 adapter interfaces + 纯 Python 逻辑
7.2: topology/__init__.py — 导出
7.3: 运行全部测试确保零回归
7.4: 写入 Phase 7 测试
```

## 3. 验收标准

- [ ] `TopologyStepExporter` 定义 STEP + topology 联合导出接口
- [ ] `SolidWorksTopologyAdapter` 定义 SW attribute ↔ PersistentTopoId 映射契约
- [ ] `NXTopologyAdapter` 定义 NX attribute journal 契约
- [ ] 96 已有测试零回归
