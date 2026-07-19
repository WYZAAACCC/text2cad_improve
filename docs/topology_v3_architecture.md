# V3 持久拓扑架构决策摘要

## 身份模型
- `TopologyIdentityDescriptorV3`: 结构化 descriptor，key = `gct3_<base64url sha256>`
- `document_lineage_id` + `feature_stable_id` 决定身份，`producer_node_id` 不进入 key
- `semantic_path`: 结构化 token tuple，拒绝 runtime index (`side_face_3`)

## 状态机
- `EntityLifecycle`: ACTIVE / SUPERSEDED / DELETED
- `BindingState`: UNBOUND / BOUND / STALE / AMBIGUOUS / UNRESOLVED
- `ProofClass`: EXACT_GENERATED_HISTORY → NONE (7 levels)
- Split → source superseded, descendants active. Merge → sources superseded, target active.

## 解析链
- `resolve_strict(context)` → 10-step verification (lineage → binding → owner → type → hash → locator)
- `resolve()` → deprecated, returns unresolved_without_context
- Matcher → fingerprint_unique, never kernel exact

## 事务
- `TopologyTransaction` → clone + validate_integrity + commit/rollback
- `validate_geometry_bindings()` → ObjectStore existence check
- `topology_mode` → forbidden/optional/required on OperationSpec

## 运行时
- `RuntimeTopoLocator.owner_body_revision_id` + `is_stale_v3()`
- `ObjectStore._revisions` + `replace()` + `get_revision()`
