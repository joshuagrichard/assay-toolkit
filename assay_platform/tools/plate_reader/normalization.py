from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def apply_blank_subtraction(df: pd.DataFrame, mode: str = "timepoint") -> pd.DataFrame:
    out = df.copy()
    out["blank_subtracted"] = out["raw_value"]
    blanks = out[out.get("role", "").astype(str).str.lower() == "blank"]
    if blanks.empty:
        return out
    if mode == "overall":
        blank_value = blanks["raw_value"].mean()
        out["blank_subtracted"] = out["raw_value"] - blank_value
    else:
        blank_by_time = blanks.groupby("time")["raw_value"].mean().rename("blank_value")
        out = out.merge(blank_by_time, on="time", how="left")
        out["blank_subtracted"] = out["raw_value"] - out["blank_value"].fillna(0)
        out = out.drop(columns=["blank_value"])
    return out


def apply_baseline_normalization(df: pd.DataFrame, source_col: str, mode: str = "delta") -> pd.DataFrame:
    out = df.copy()
    baseline = out.sort_values("time").groupby("well")[source_col].first().rename("baseline_value")
    out = out.merge(baseline, on="well", how="left")
    if mode == "fold":
        out["baseline_normalized"] = out[source_col] / out["baseline_value"].replace(0, np.nan)
    elif mode == "percent":
        out["baseline_normalized"] = 100.0 * out[source_col] / out["baseline_value"].replace(0, np.nan)
    else:
        out["baseline_normalized"] = out[source_col] - out["baseline_value"]
    return out.drop(columns=["baseline_value"])


def apply_control_normalization(df: pd.DataFrame, source_col: str, mode: str = "timepoint") -> pd.DataFrame:
    out = df.copy()
    roles = out.get("role", "").astype(str).str.lower()
    controls = out[roles.isin(["vehicle", "control"])]
    out["control_normalized"] = out[source_col]
    if controls.empty:
        return out
    group_cols = ["time"] if mode == "timepoint" else []
    if group_cols:
        control_ref = controls.groupby(group_cols)[source_col].mean().rename("control_value")
        out = out.merge(control_ref, on=group_cols, how="left")
    else:
        out["control_value"] = controls[source_col].mean()
    out["control_normalized"] = out[source_col] / out["control_value"].replace(0, np.nan)
    return out.drop(columns=["control_value"])


def process_measurements(labeled: pd.DataFrame, settings: dict[str, Any]) -> pd.DataFrame:
    out = labeled.copy()
    value_col = "raw_value"
    blank_settings = settings.get("blank_subtraction", {})
    if blank_settings.get("enabled"):
        out = apply_blank_subtraction(out, blank_settings.get("mode", "timepoint"))
        value_col = "blank_subtracted"
    baseline_settings = settings.get("baseline_normalization", {})
    if baseline_settings.get("enabled"):
        out = apply_baseline_normalization(out, value_col, baseline_settings.get("mode", "delta"))
        value_col = "baseline_normalized"
    control_settings = settings.get("control_normalization", {})
    if control_settings.get("enabled"):
        out = apply_control_normalization(out, value_col, control_settings.get("mode", "timepoint"))
        value_col = "control_normalized"
    out["analysis_value"] = out[value_col]
    out["analysis_value_source"] = value_col
    return out

