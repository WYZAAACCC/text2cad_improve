"""临时验证：数据集三项落盘（T/CCAD/L）— helper 单测。

只测 _write_pipeline_log（main.py 新增函数），import main 有 OUT_ROOT.mkdir 副作用，无害。
"""
import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
SERVER = _HERE.parent / "app" / "text-to-cad" / "server"
sys.path.insert(0, str(SERVER))

import main  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    (d / "llm_raw.json").write_text("{}", encoding="utf-8")
    (d / "output.step").write_text("x", encoding="utf-8")
    (d / "req_param_report.json").write_text("{}", encoding="utf-8")

    # ok=True：artifacts 扫描含已有产物，stages 透传
    main._write_pipeline_log(d, ok=True, stages={
        "route": "generative_cad_ir", "stl": {"ok": True}})
    log = json.loads((d / "pipeline_log.json").read_text(encoding="utf-8"))
    assert log["ok"] is True
    assert log["stages"]["route"] == "generative_cad_ir"
    for name in ("llm_raw.json", "output.step", "req_param_report.json"):
        assert name in log["artifacts"], f"missing {name} in artifacts"
    print("helper ok=True  PASS  artifacts =", log["artifacts"])

    # ok=False：error 记录
    main._write_pipeline_log(d, ok=False, error="boom")
    log2 = json.loads((d / "pipeline_log.json").read_text(encoding="utf-8"))
    assert log2["ok"] is False and log2["error"] == "boom"
    print("helper ok=False PASS  error =", log2["error"])

    # 空 stages / 空目录：不抛异常
    empty = Path(td) / "empty"
    empty.mkdir()
    main._write_pipeline_log(empty, ok=False)
    log3 = json.loads((empty / "pipeline_log.json").read_text(encoding="utf-8"))
    assert log3["stages"] == {} and log3["artifacts"] == []
    print("helper empty    PASS")

print("ALL OK")
