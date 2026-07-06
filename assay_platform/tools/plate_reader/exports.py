from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import zipfile

import pandas as pd


def prism_wide(metrics: pd.DataFrame, metric: str = "endpoint", group_col: str = "condition") -> pd.DataFrame:
    if metrics.empty or metric not in metrics.columns:
        return pd.DataFrame()
    df = metrics.copy()
    if group_col not in df.columns:
        group_col = "group" if "group" in df.columns else "well"
    if "replicate" in df.columns:
        df["replicate_label"] = df["replicate"].astype(str)
    else:
        df["replicate_label"] = ""
    df.loc[df["replicate_label"].str.strip() == "", "replicate_label"] = df["well"]
    wide_cols = {}
    for group, g in df.groupby(group_col):
        values = g[metric].reset_index(drop=True)
        wide_cols[str(group) or "unlabeled"] = values
    return pd.DataFrame(wide_cols)


def write_exports(output_dir: Path,
                  raw_tidy: pd.DataFrame,
                  labeled: pd.DataFrame,
                  processed: pd.DataFrame,
                  summary: pd.DataFrame,
                  metrics: pd.DataFrame,
                  stats_table: pd.DataFrame,
                  plate_map: pd.DataFrame,
                  settings: dict[str, Any]) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "raw_tidy_csv": output_dir / "raw_tidy.csv",
        "labeled_tidy_csv": output_dir / "labeled_tidy.csv",
        "processed_tidy_csv": output_dir / "processed_tidy.csv",
        "summary_csv": output_dir / "summary.csv",
        "metrics_csv": output_dir / "well_metrics.csv",
        "stats_csv": output_dir / "statistics.csv",
        "plate_map_csv": output_dir / "plate_map.csv",
        "plate_map_json": output_dir / "plate_map.json",
        "prism_csv": output_dir / "prism_wide.csv",
        "settings_json": output_dir / "analysis_settings.json",
    }
    raw_tidy.to_csv(paths["raw_tidy_csv"], index=False)
    labeled.to_csv(paths["labeled_tidy_csv"], index=False)
    processed.to_csv(paths["processed_tidy_csv"], index=False)
    summary.to_csv(paths["summary_csv"], index=False)
    metrics.to_csv(paths["metrics_csv"], index=False)
    stats_table.to_csv(paths["stats_csv"], index=False)
    plate_map.to_csv(paths["plate_map_csv"], index=False)
    paths["plate_map_json"].write_text(plate_map.to_json(orient="records", indent=2), encoding="utf-8")
    prism_wide(metrics, settings.get("export_metric", "endpoint")).to_csv(paths["prism_csv"], index=False)
    paths["settings_json"].write_text(json.dumps(settings, indent=2), encoding="utf-8")

    zip_path = output_dir / "plate_reader_exports.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for key, path in paths.items():
            if key == "zip" or path == zip_path or not path.exists():
                continue
            zip_file.write(path, arcname=path.name)
    paths["zip"] = zip_path
    return paths
