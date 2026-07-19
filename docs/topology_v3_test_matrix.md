# V3 测试覆盖矩阵

## 测试文件 (11 files, 76 tests)

| 文件 | Tests | 覆盖 |
|------|-------|------|
| test_identity_model | 23 | V3 descriptor, semantic_path, migration reader |
| test_registry_strict_resolution | 10 | lineage, delta, sidecar restore |
| test_matcher_and_policies | 5 | fingerprint, CAE gate, consumer policies |
| test_shape_binding_revision | 9 | ObjectStore revision, locator staleness |
| test_geo_topo_transaction | 4 | transaction geometry validation |
| test_topology_delta_required | 5 | topology_mode enforcement |
| test_semantic_naming_entity_type | 5 | _infer_entity_type evidence |
| test_topology_mutations | 3 | locator tampering, owner revision |
| test_sidecar_v3 | 5 | byte-identical, hash mismatch, migration |
| test_registry_reindex | 2 | supersede overwrite, restore reindex |
| test_consumer_policies | 5 | exhaustive policy coverage |

## 待添加 (需 CadQuery/OCP 环境)
- test_history_extrude/revolve/boolean
- test_secondary_features
- test_cross_backend_proof
- test_revision_perturbations
- test_cae_preflight_strict
