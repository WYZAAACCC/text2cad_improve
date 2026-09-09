# regen_800

- schema_version: `regen_v1`
- generated_at: 2026-08-29T02:12:48+00:00
- records: 800

## single

| 指标 | 值 |
|---|---|
| runs | 200 |
| regen_success | 0.96 |

## double

| 指标 | 值 |
|---|---|
| runs | 200 |
| regen_success | 0.9 |

## triple_five

| 指标 | 值 |
|---|---|
| runs | 200 |
| regen_success | 0.845 |

## cross_feature

| 指标 | 值 |
|---|---|
| runs | 200 |
| regen_success | 0.915 |

## far

| 指标 | 值 |
|---|---|
| runs | 250 |
| regen_success | 1.0 |

## mid

| 指标 | 值 |
|---|---|
| runs | 172 |
| regen_success | 0.936 |

## near

| 指标 | 值 |
|---|---|
| runs | 378 |
| regen_success | 0.828 |

## overall

| 指标 | 值 |
|---|---|
| overall | True |
| runs | 800 |
| regen_success | 0.905 |


## 记录示例

```json
{
  "perturbation_id": "T01_P003",
  "task_id": "T01",
  "category": "cross_feature",
  "margin": 0.0562,
  "margin_group": "mid",
  "regenerated_ok": false,
  "quality_ok": true,
  "failed_checks": [],
  "reason": "重建失败/不可行",
  "ok": false,
  "record_id": "regen_a5147f602ba7",
  "collected_at": "2026-08-29T02:12:48+00:00",
  "schema_version": "regen_v1"
}
```