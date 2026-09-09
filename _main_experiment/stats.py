"""Statistical helpers for benchmark reporting."""

from __future__ import annotations

import math
import random
from typing import Any, Iterable, Sequence

import numpy as np


def bootstrap_ci(
    values: Sequence[float],
    *,
    n_bootstrap: int = 10000,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict[str, float]:
    if not values:
        return {"mean": float("nan"), "low": float("nan"), "high": float("nan")}
    rng = random.Random(seed)
    arr = list(values)
    means = []
    for _ in range(n_bootstrap):
        sample = [arr[rng.randrange(len(arr))] for _ in range(len(arr))]
        means.append(sum(sample) / len(sample))
    means.sort()
    low_idx = max(0, int(round(alpha / 2 * n_bootstrap)) - 1)
    high_idx = min(n_bootstrap - 1, int(round((1 - alpha / 2) * n_bootstrap)) - 1)
    return {
        "mean": round(sum(arr) / len(arr), 6),
        "low": round(means[low_idx], 6),
        "high": round(means[high_idx], 6),
    }


def cluster_bootstrap_ci(
    task_groups: dict[str, Sequence[float]],
    *,
    n_bootstrap: int = 10000,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict[str, float]:
    """Cluster bootstrap over tasks (paper P63): resample tasks, keep their runs."""
    task_ids = list(task_groups.keys())
    if not task_ids:
        return {"mean": float("nan"), "low": float("nan"), "high": float("nan")}
    rng = random.Random(seed)
    means = []
    for _ in range(n_bootstrap):
        vals = []
        for _ in task_ids:
            tid = task_ids[rng.randrange(len(task_ids))]
            vals.extend(task_groups[tid])
        means.append(sum(vals) / len(vals) if vals else 0.0)
    means.sort()
    low_idx = max(0, int(round(alpha / 2 * n_bootstrap)) - 1)
    high_idx = min(n_bootstrap - 1, int(round((1 - alpha / 2) * n_bootstrap)) - 1)
    all_vals = [v for vs in task_groups.values() for v in vs]
    return {
        "mean": round(sum(all_vals) / len(all_vals), 6) if all_vals else float("nan"),
        "low": round(means[low_idx], 6),
        "high": round(means[high_idx], 6),
    }


def wilcoxon_signed_rank(
    before: Sequence[float],
    after: Sequence[float],
) -> dict[str, Any]:
    if len(before) != len(after):
        raise ValueError("before and after must have the same length")
    try:
        from scipy.stats import wilcoxon
        stat, p_value = wilcoxon(list(before), list(after), alternative="two-sided")
        return {"statistic": float(stat), "p_value": float(p_value), "method": "scipy"}
    except Exception:
        # Normal-approximation fallback over signed ranks.
        diffs = [a - b for a, b in zip(before, after) if a != b]
        if not diffs:
            return {"statistic": 0.0, "p_value": 1.0, "method": "fallback"}
        ranked = {}
        sorted_diffs = sorted(diffs, key=abs)
        i = 0
        while i < len(sorted_diffs):
            j = i
            while j + 1 < len(sorted_diffs) and abs(sorted_diffs[j + 1]) == abs(sorted_diffs[i]):
                j += 1
            rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranked[id(sorted_diffs[k])] = rank if sorted_diffs[k] > 0 else -rank
            i = j + 1
        w = sum(ranked[id(d)] for d in diffs)
        n = len(diffs)
        mu = n * (n + 1) / 4
        sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
        z = (abs(w) - 0.5) / sigma if sigma else 0.0
        p = 2 * (1 - _normal_cdf(z))
        return {"statistic": float(w), "p_value": float(p), "method": "fallback"}


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def cliffs_delta(x: Sequence[float], y: Sequence[float]) -> float:
    if not x or not y:
        return float("nan")
    greater = sum(1 for xi in x for yi in y if xi > yi)
    less = sum(1 for xi in x for yi in y if xi < yi)
    return (greater - less) / (len(x) * len(y))


def holm_bonferroni(p_values: Sequence[float], alpha: float = 0.05) -> list[bool]:
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    n = len(indexed)
    rejected = [False] * n
    for i, (original_idx, p) in enumerate(indexed):
        threshold = alpha / (n - i)
        rejected[original_idx] = p <= threshold
        if not rejected[original_idx]:
            break
    return rejected


def glmm_odds_ratio(
    data: Sequence[dict[str, Any]],
    *,
    method_col: str = "method",
    success_col: str = "successes",
    total_col: str = "totals",
    task_col: str = "task",
) -> dict[str, Any]:
    """Estimate method odds ratios with a Bayesian binomial mixed GLM."""
    try:
        import pandas as pd
        from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM

        rows = []
        for rec in data:
            successes = int(rec[success_col])
            totals = int(rec[total_col])
            for _ in range(successes):
                rows.append({method_col: rec[method_col], task_col: rec[task_col], "y": 1})
            for _ in range(max(0, totals - successes)):
                rows.append({method_col: rec[method_col], task_col: rec[task_col], "y": 0})
        frame = pd.DataFrame(rows)
        if frame.empty:
            raise ValueError("no observations")
        model = BinomialBayesMixedGLM.from_formula(
            "y ~ C(" + method_col + ")",
            {task_col: f"0 + C({task_col})"},
            frame,
            vcp_p=1,
            fe_p=2,
        )
        fitted = model.fit_vb()
        fe_mean = list(fitted.fe_mean)
        _fe_sd = getattr(fitted, "fe_sd", None)
        fe_sd = list(_fe_sd) if _fe_sd is not None else []
        names = list(model.exog_names)
        baseline = sorted(set(frame[method_col]))[0]
        result: dict[str, Any] = {
            "baseline_method": str(baseline),
            "odds_ratios": {},
            "method": "BinomialBayesMixedGLM",
        }
        for i, (name, value) in enumerate(zip(names, fe_mean)):
            if name.startswith("C(method)[T."):
                key = name.split(".")[1][:-1]
                sd = fe_sd[i] if i < len(fe_sd) else None
                or_value = float(math.exp(value))
                entry: dict[str, Any] = {"or": round(or_value, 4)}
                if sd is not None and sd > 0:
                    z = 1.959963984540054
                    entry["ci_low"] = round(float(math.exp(value - z * sd)), 4)
                    entry["ci_high"] = round(float(math.exp(value + z * sd)), 4)
                result["odds_ratios"][key] = entry
        return result
    except Exception as exc:  # noqa: BLE001
        return {"method": "not_computed", "error": str(exc)[:300]}
