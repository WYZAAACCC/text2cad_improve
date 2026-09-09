# tools_160x5

- schema_version: `tool_v1`
- generated_at: 2026-08-30T03:59:08+00:00
- records: 2400

## fixed

| 指标 | 值 |
|---|---|
| runs | 800 |
| tool_selection_f1 | 1.0 |
| param_binding_accuracy | 1.0 |
| multi_tool_completion | 0.75 |
| result_accuracy | 0.75 |
| new_tool_call_rate | 0.0 |

## mcp_agent

| 指标 | 值 |
|---|---|
| runs | 800 |
| tool_selection_f1 | 0.8286 |
| param_binding_accuracy | 1.0 |
| multi_tool_completion | 0.9337 |
| result_accuracy | 0.9762 |
| new_tool_call_rate | 0.9 |

## llm_code

| 指标 | 值 |
|---|---|
| runs | 800 |
| tool_selection_f1 | 0.3917 |
| param_binding_accuracy | 0.5162 |
| multi_tool_completion | 0.5162 |
| result_accuracy | 0.3312 |
| new_tool_call_rate | 0.0 |


## 记录示例

```json
{
  "tool_task_id": "T01_TOOL_anomaly",
  "category": "anomaly",
  "selected": [
    "measure_disc_dimensions"
  ],
  "ordered_selected": [
    "measure_disc_dimensions"
  ],
  "expected": [
    "measure_disc_dimensions"
  ],
  "binding_ok": true,
  "multi_complete": true,
  "result_ok": true,
  "new_tool_called": false,
  "unregistered_tool": false,
  "interface": "fixed",
  "seed": 0,
  "record_id": "tool_6001b95f3368",
  "collected_at": "2026-08-30T03:59:07+00:00",
  "schema_version": "tool_v1"
}
```