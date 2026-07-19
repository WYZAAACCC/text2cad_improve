# Consumer Policy 参考

## ResolutionQuality (低→高)
| Rank | Quality |
|------|---------|
| 0 | UNRESOLVED |
| 1 | FINGERPRINT_UNIQUE |
| 2 | SET_EXPANSION |
| 3 | DETERMINISTIC_SEMANTIC |
| 6 | EXACT_KERNEL_HISTORY |

## 预定义策略
| Consumer | Min Quality | Allows Ambiguity |
|----------|------------|------------------|
| debug_visualization | FINGERPRINT_UNIQUE | Yes |
| decorative_fillet | FINGERPRINT_UNIQUE | No |
| decorative_chamfer | FINGERPRINT_UNIQUE | No |
| required_mechanical_feature | DETERMINISTIC_SEMANTIC | No |
| assembly_constraint | DETERMINISTIC_SEMANTIC | No |
| cae_load | DETERMINISTIC_SEMANTIC | No |
| cae_constraint | DETERMINISTIC_SEMANTIC | No |
| cae_contact | EXACT_KERNEL_HISTORY | No |
| cae_mesh_control | DETERMINISTIC_SEMANTIC | Yes |
| manufacturing_output | EXACT_KERNEL_HISTORY | No |

## 未知处理
- Unknown method → ValueError (fail-closed)
- Unknown consumer → debug_visualization fallback (safe default)
