# infeasible_120

- schema_version: `infeasible_v1`
- generated_at: 2026-08-29T22:46:23+00:00
- records: 240

## overall

| 指标 | 值 |
|---|---|
| with_constraints | True |
| runs | 120 |
| correct_rejection_rate | 1.0 |

## overall

| 指标 | 值 |
|---|---|
| with_constraints | False |
| runs | 120 |
| correct_rejection_rate | 1.0 |

## hole_out_of_bounds

| 指标 | 值 |
|---|---|
| runs | 48 |
| correct_rejection_rate | 1.0 |

## slot_pitch_insufficient

| 指标 | 值 |
|---|---|
| runs | 48 |
| correct_rejection_rate | 1.0 |

## slot_depth_over_rim

| 指标 | 值 |
|---|---|
| runs | 48 |
| correct_rejection_rate | 1.0 |

## fillet_unconstructable

| 指标 | 值 |
|---|---|
| runs | 48 |
| correct_rejection_rate | 1.0 |

## hard_constraint_conflict

| 指标 | 值 |
|---|---|
| runs | 48 |
| correct_rejection_rate | 1.0 |

- reason_distribution: {'structured_precheck': 96, 'validation_failed': 144}

## 记录示例

```json
{
  "infeasible_id": "INF_00_hole_out_of_bounds",
  "category": "hole_out_of_bounds",
  "with_constraints": true,
  "correct_rejected": true,
  "delivered": false,
  "rejection": "structured_precheck",
  "reason": "减重孔分布半径 300.0 > 轮缘外半径 250.0",
  "record_id": "infeasible_ae1da5740a11",
  "collected_at": "2026-08-29T22:46:23+00:00",
  "schema_version": "infeasible_v1"
}
```