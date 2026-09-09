from _main_experiment.stats import (
    bootstrap_ci,
    cliffs_delta,
    glmm_odds_ratio,
    holm_bonferroni,
    wilcoxon_signed_rank,
)


def test_bootstrap_ci_bounds():
    ci = bootstrap_ci([1.0, 2.0, 3.0, 4.0, 5.0], n_bootstrap=200, seed=1)
    assert ci["low"] <= ci["mean"] <= ci["high"]


def test_wilcoxon_signed_rank_returns_p():
    result = wilcoxon_signed_rank([1.0, 2.0, 3.0], [1.1, 2.2, 3.3])
    assert "p_value" in result


def test_cliffs_delta():
    assert cliffs_delta([3.0, 4.0], [1.0, 2.0]) == 1.0


def test_holm_bonferroni():
    rejected = holm_bonferroni([0.01, 0.02, 0.5], alpha=0.05)
    assert rejected == [True, True, False]


def test_glmm_odds_ratio_returns_or():
    data = []
    for task in range(5):
        for method in ("A", "B"):
            data.append({
                "method": method,
                "task": task,
                "successes": 8 if method == "B" else 5,
                "totals": 10,
            })
    result = glmm_odds_ratio(data)
    assert result["method"] == "BinomialBayesMixedGLM"
    assert result["odds_ratios"]["B"] > 1.0
