from __future__ import annotations

from typing import Any

import pandas as pd
from scipy import stats


def basic_stats(metrics: pd.DataFrame, settings: dict[str, Any] | None = None) -> pd.DataFrame:
    settings = settings or {}
    metric = settings.get("metric", "endpoint")
    group_col = settings.get("group_by", "condition")
    if metric not in metrics.columns or group_col not in metrics.columns:
        return pd.DataFrame()
    groups = [(name, g[metric].dropna().astype(float)) for name, g in metrics.groupby(group_col)]
    groups = [(name, vals) for name, vals in groups if len(vals) > 0]
    if len(groups) < 2:
        return pd.DataFrame()
    if len(groups) == 2:
        stat, pval = stats.ttest_ind(groups[0][1], groups[1][1], equal_var=False)
        return pd.DataFrame(
            [{"test": "Welch t-test", "metric": metric, "group_a": groups[0][0], "group_b": groups[1][0], "statistic": stat, "p_value": pval}]
        )
    stat, pval = stats.f_oneway(*[vals for _, vals in groups])
    return pd.DataFrame([{"test": "one-way ANOVA", "metric": metric, "groups": ", ".join(str(name) for name, _ in groups), "statistic": stat, "p_value": pval}])

