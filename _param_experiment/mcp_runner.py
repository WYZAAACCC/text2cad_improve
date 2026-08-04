"""DiskCAD-MCP 独立 CLI runner — 对任意建模任务目录执行 MCP 质量检查。

把论文的 DiskCAD-MCP 外层质量门（post-processing）接入主流程产物：
对任意 `server/output/<hash>/`（含 raw_fixed.json + output.step）运行
agentic loop，LLM 按工具说明/schema 发现调用检查工具，输出工程验收报告。

零主程序改动：不改 integrations/engineering_tools/src/，不改 server/main.py。
实现方式：运行时把 mcp_tools.BASE 指向目标目录（模块级赋值，进程内副作用），
工具 handler 的 _base_dir(args) 回退到 BASE，因此 LLM 工具调用省略 base_dir 时
默认读目标目录。

用法:
  .conda/python.exe _param_experiment/mcp_runner.py [--base-dir <dir> | --latest] \
        [--task <自然语言检查任务>] [--out <报告json>] [--max-rounds N]
  --base-dir  目标建模产物目录（须含 raw_fixed.json + output.step）
  --latest    自动选 server/output/ 下最新含 raw_fixed.json 的目录
  --task      自然语言质量检查任务（默认完整质量检查）
  --out       报告 JSON 输出路径（默认 _param_experiment/output/mcp_server/qa_<hash>.json）
  --max-rounds agentic loop 最大轮数（默认 16）

退出码: accepted=True → 0；失败/未收敛 → 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 确保实验区可导入
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from mcp_server import run_quality_assurance  # noqa: E402
import mcp_tools  # noqa: E402

# 主流程建模产物根目录
_OUT_ROOT = (_HERE.parent / "app" / "text-to-cad" / "server" / "output").resolve()
# 基准目录（默认，与 mcp_tools/mcp_server 一致）
_DEFAULT_BASE = _OUT_ROOT / "b572661c219c4952"

# 默认完整质量检查任务
DEFAULT_TASK = (
    "请对该涡轮盘执行完整质量检查：实体有效性、外径/中心孔直径/轴向厚度、"
    "榫槽数量、齿数、槽深、齿面角、周向节距与最小剩余材料、槽深与轮缘厚度约束、"
    "STEP 导出-回读体积一致性。汇总结果并给出工程验收结论。"
)


def _resolve_base_dir(base_dir: str | None, latest: bool) -> Path:
    """解析目标目录：--base-dir 显式 / --latest 自动 / 默认基准。"""
    if base_dir:
        p = Path(base_dir).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"目录不存在: {p}")
        return p
    if latest:
        candidates = []
        for d in _OUT_ROOT.iterdir():
            if d.is_dir() and (d / "raw_fixed.json").exists() and (d / "output.step").exists():
                candidates.append(d)
        if not candidates:
            raise FileNotFoundError(f"{_OUT_ROOT} 下没有含 raw_fixed.json+output.step 的任务目录")
        return max(candidates, key=lambda d: d.stat().st_mtime)
    return _DEFAULT_BASE


def _validate_base_dir(base: Path) -> None:
    """校验目标目录必须含 Disk-G-CAD 与 STEP，缺则明确报错。"""
    missing = []
    if not (base / "raw_fixed.json").exists():
        missing.append("raw_fixed.json")
    if not (base / "output.step").exists():
        missing.append("output.step")
    if missing:
        raise FileNotFoundError(
            f"目标目录 {base} 缺少: {', '.join(missing)}（MCP 检查需要 Disk-G-CAD + STEP）"
        )


def run_mcp_quality_assurance(
    base_dir: str | Path,
    task: str = DEFAULT_TASK,
    max_rounds: int = 16,
    out_path: str | Path | None = None,
) -> dict:
    """对任意建模任务目录执行 MCP 质量检查。

    返回 run_quality_assurance 的结果 dict（含 tool_sequence / final_report /
    accepted / termination）。out_path 给定则保存报告 JSON。
    """
    base = Path(base_dir).resolve()
    _validate_base_dir(base)

    # 运行时把工具默认基准指向目标目录（不改源码；进程内副作用）
    mcp_tools.BASE = base

    result = run_quality_assurance(task, str(base), max_rounds=max_rounds)

    if out_path is None:
        out_path = _HERE / "output" / "mcp_server" / f"qa_{base.name}.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def _print_summary(result: dict, base: Path) -> None:
    print(f"\n[base_dir] {base}")
    seq = result.get("tool_sequence", [])
    print(f"[tool_sequence] {len(seq)} calls")
    for i, s in enumerate(seq, 1):
        ok = s["result"].get("ok")
        st = "OK" if ok is True else "FAIL"
        print(f"  [{i}] {s['tool']:42s} -> {st}")
        r = s["result"]
        for k in ("count", "volume_mm3", "outer_diameter_mm", "pitch_mm",
                  "teeth_count", "slot_depth_mm", "accepted", "reason"):
            if k in r:
                print(f"        {k} = {r[k]}")
    print(f"[termination] {result.get('termination')}")
    print(f"[accepted] {result.get('accepted')}")
    if result.get("error"):
        print(f"[error] {result['error']}")
    if result.get("final_report"):
        report = result["final_report"]
        # 仅打印验收结论行；LLM 报告可能含 emoji（GBK 终端崩），转码过滤不可编码字符
        for line in report.splitlines():
            if "验收结论" in line or "accept" in line.lower():
                safe = line.encode("gbk", errors="replace").decode("gbk")
                print(f"[verdict] {safe.strip()}")
    print(f"[report] {result.get('report_path', '(saved)')}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DiskCAD-MCP 质量检查 runner（对任意建模产物目录）")
    ap.add_argument("--base-dir", default=None, help="目标目录（含 raw_fixed.json + output.step）")
    ap.add_argument("--latest", action="store_true", help="自动选 server/output/ 最新任务目录")
    ap.add_argument("--task", default=DEFAULT_TASK, help="自然语言质量检查任务")
    ap.add_argument("--out", default=None, help="报告 JSON 输出路径")
    ap.add_argument("--max-rounds", type=int, default=16, help="agentic loop 最大轮数")
    args = ap.parse_args(argv)

    try:
        base = _resolve_base_dir(args.base_dir, args.latest)
        result = run_mcp_quality_assurance(
            base, task=args.task, max_rounds=args.max_rounds, out_path=args.out,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    result["report_path"] = str(
        Path(args.out) if args.out else _HERE / "output" / "mcp_server" / f"qa_{base.name}.json"
    )
    _print_summary(result, base)

    return 0 if result.get("accepted") is True else 1


if __name__ == "__main__":
    sys.exit(main())
