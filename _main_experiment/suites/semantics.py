"""320 semantically-equivalent NL instructions (8 rewrite categories × 40 tasks)."""
from __future__ import annotations

import re
from typing import Any

from ..config import ExperimentConfig
from ..schemas import TaskSpec

_TERM_MAP = [
    ("外径", "最大外径"),
    ("中心孔直径", "中心孔径"),
    ("轴向最大厚度", "轴向总厚"),
    ("轮毂半厚", "轮毂半高"),
    ("轮缘半厚", "轮缘半高"),
    ("枞树形榫槽", "冷杉齿榫槽"),
    ("环槽槽宽", "环槽宽度"),
    ("环槽槽深", "环槽深度"),
    ("孔径", "直径"),
]

_FUZZY = ("约", "左右", "近似")


def _clauses(prompt: str) -> list[str]:
    body = prompt.split("。", 1)[0]
    return [c for c in body.split("，") if c.strip()]


def _rewrite(prompt: str, category: str, idx: int) -> str:
    tail = "。参考几何，非适航件。"
    if category == "baseline":
        return prompt
    if category == "order_change":
        parts = _clauses(prompt)
        if len(parts) > 3:
            first, rest = parts[0], parts[1:]
            mid = len(rest) // 2
            if idx % 2 == 0:
                rest = rest[mid:] + rest[:mid]
            else:
                rest = rest[1:] + rest[:1]
            return "，".join([first] + rest) + tail
    if category == "term_swap":
        out = prompt
        for a, b in _TERM_MAP:
            if a in out and b not in out:
                out = out.replace(a, b, 1)
                break
        return out
    if category == "unit_mix":
        m = re.search(r"外径(\d+)mm", prompt)
        if m:
            cm = int(m.group(1)) / 10
            return prompt.replace(f"外径{m.group(1)}mm", f"外径{cm:g}cm", 1)
        return prompt
    if category == "ratio_abs":
        m = re.search(r"轮毂半厚(\d+)mm", prompt)
        if m:
            od = re.search(r"外径(\d+)mm", prompt)
            pct = int(m.group(1)) * 100 / int(od.group(1)) if od else 10.0
            return prompt.replace(
                f"轮毂半厚{m.group(1)}mm",
                f"轮毂半厚约为外径的{pct:.1f}%",
                1,
            )
        return prompt
    if category == "fuzzy":
        out = prompt
        for name in ("槽深", "喉部半宽", "孔径", "分布半径"):
            m = re.search(rf"{name}(\d+)mm", out)
            if m:
                out = out.replace(f"{name}{m.group(1)}mm",
                                  f"{name}{_FUZZY[idx % 3]}{m.group(1)}mm", 1)
                break
        return out
    if category == "split_sentence":
        return prompt.replace("，", "；", 2).replace("；", "，", 1) if "，" in prompt else prompt
    if category == "table_conflict":
        return prompt[:-len("。参考几何，非适航件。")] + "。注意：随附表格中外径一栏填写为480mm。" + tail
    return prompt


_CATEGORIES = (
    "baseline", "order_change", "term_swap", "unit_mix",
    "ratio_abs", "fuzzy", "split_sentence", "table_conflict",
)


def build_tasks(tasks: list[TaskSpec]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for task in tasks:
        for cat in _CATEGORIES:
            out.append({
                "task_id": task.task_id,
                "semantic_id": f"{task.task_id}_{cat}",
                "category": cat,
                "prompt": _rewrite(task.prompt, cat, 0),
                "normalized_params": task.normalized_params,
            })
    return out


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = max(1, len(results))
    param_ok = sum(1 for r in results if r.get("param_consistent"))
    param_clean_ok = sum(1 for r in results if r.get("param_consistent_clean"))
    param_clean_den = sum(1 for r in results if (r.get("param_checked_clean") or 0) > 0)
    fdg_iso = sum(1 for r in results if r.get("fdg_isomorphic"))
    eng_ok = sum(1 for r in results if r.get("engineering_ok"))
    return {
        "runs": len(results),
        "param_extract_consistency": round(param_ok / total, 4),
        "param_extract_consistency_clean": (
            round(param_clean_ok / param_clean_den, 4) if param_clean_den else None
        ),
        "invalid_measurements_skipped": sum(
            int(r.get("param_skipped_invalid") or 0) for r in results
        ),
        "fdg_isomorphism_rate": round(fdg_iso / total, 4),
        "engineering_success_rate": round(eng_ok / total, 4),
    }
