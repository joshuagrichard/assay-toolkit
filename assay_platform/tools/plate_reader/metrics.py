from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def auc_for_trace(trace: pd.DataFrame, value_col: str, start: float | None = None, end: float | None = None) -> float:
    t = trace.sort_values("time").copy()
    if start is not None:
        t = t[t["time"] >= start]
    if end is not None:
        t = t[t["time"] <= end]
    t = t.dropna(subset=["time", value_col])
    if len(t) < 2:
        return np.nan
    return float(np.trapz(t[value_col].astype(float), t["time"].astype(float)))


def slope_for_trace(trace: pd.DataFrame, value_col: str, start: float | None = None, end: float | None = None) -> float:
    t = trace.sort_values("time").copy()
    if start is not None:
        t = t[t["time"] >= start]
    if end is not None:
        t = t[t["time"] <= end]
    t = t.dropna(subset=["time", value_col])
    if len(t) < 2:
        return np.nan
    slope, _ = np.polyfit(t["time"].astype(float), t[value_col].astype(float), 1)
    return float(slope)


def calculate_well_metrics(processed: pd.DataFrame, settings: dict[str, Any] | None = None) -> pd.DataFrame:
    settings = settings or {}
    metric_settings = settings.get("metrics", {})
    start = metric_settings.get("start_time")
    end = metric_settings.get("end_time")
    early_end = metric_settings.get("early_end_time")
    late_start = metric_settings.get("late_start_time")
    value_col = metric_settings.get("value_column", "analysis_value")
    rows = []
    label_cols = ["condition", "treatment", "dose", "replicate", "group", "role"]
    for well, trace in processed.groupby("well"):
        trace = trace.sort_values("time")
        last = trace.dropna(subset=[value_col]).tail(1)
        base = {"well": well}
        for col in label_cols:
            if col in trace.columns:
                base[col] = trace[col].iloc[0]
        base.update(
            {
                "endpoint": float(last[value_col].iloc[0]) if not last.empty else np.nan,
                "max_response": float(trace[value_col].max()),
                "min_response": float(trace[value_col].min()),
                "auc": auc_for_trace(trace, value_col, start, end),
                "early_auc": auc_for_trace(trace, value_col, start, early_end) if early_end is not None else np.nan,
                "late_auc": auc_for_trace(trace, value_col, late_start, end) if late_start is not None else np.nan,
                "slope": slope_for_trace(trace, value_col, start, end),
            }
        )
        rows.append(base)
    return pd.DataFrame(rows)


def summarize_replicates(processed: pd.DataFrame, value_col: str = "analysis_value") -> pd.DataFrame:
    group_cols = [col for col in ["condition", "treatment", "dose", "group", "time"] if col in processed.columns]
    if not group_cols:
        group_cols = ["time"]
    summary = processed.groupby(group_cols)[value_col].agg(["mean", "std", "count"]).reset_index()
    summary = summary.rename(columns={"count": "n"})
    summary["sem"] = summary["std"] / np.sqrt(summary["n"].replace(0, np.nan))
    return summary

