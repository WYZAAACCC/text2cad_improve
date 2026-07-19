# V1→V2→V3 迁移指南

## Key 格式识别
- v1: `gct:v1:<doc[:12]>:<comp>:<root>:<producer>:<type>:<role>`
- v2: `gct2_<43-char base64url>` (不可逆，需 sidecar descriptor)
- v3: `gct3_<43-char base64url>` (可逆，descriptor 存储在 record 中)

## 迁移规则
- Reader: 支持 v1/v2/v3 (parse_persistent_id_key)
- Writer: 只写 v3
- v1: 标记 legacy_unverified，document_id 已截断
- v2: 标记 v2_irreversible_no_descriptor，需旧 artifact 做迁移匹配
- CAD adapter: 禁止再用 from_compact() 解析新 key

## 代码迁移
- `_make_compact_id()` → 返回 `(key, descriptor_dict)`
- `make_persistent_id_v2()` → deprecated，使用 `make_persistent_id_v3()`
- 所有 semantic_naming name_* 函数已切换到 V3 key
