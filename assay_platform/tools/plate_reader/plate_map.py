from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from assay_platform.tools.plate_reader.parser import WELLS_96, canonical_well

PLATE_MAP_COLUMNS = [
    "well",
    "condition",
    "treatment",
    "dose",
    "replicate",
    "group",
    "role",
    "notes",
]


def empty_plate_map() -> pd.DataFrame:
    return pd.DataFrame([{column: "" for column in PLATE_MAP_COLUMNS} | {"well": well} for well in WELLS_96])


def normalize_plate_map(records: list[dict[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(records).copy()
    if df.empty:
        return empty_plate_map()
    if "well" not in df.columns:
        raise ValueError("Plate map must include a well column.")
    df["well"] = df["well"].map(canonical_well)
    df = df.dropna(subset=["well"])
    for column in PLATE_MAP_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df = df[PLATE_MAP_COLUMNS].drop_duplicates("well", keep="last")
    merged = empty_plate_map().drop(columns=[c for c in PLATE_MAP_COLUMNS if c != "well"]).merge(
        df, on="well", how="left"
    )
    for column in PLATE_MAP_COLUMNS:
        if column != "well":
            merged[column] = merged[column].fillna("")
    return merged[PLATE_MAP_COLUMNS]


def load_plate_map(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".json":
        return normalize_plate_map(pd.read_json(path))
    return normalize_plate_map(pd.read_csv(path))


def merge_plate_map(tidy: pd.DataFrame, plate_map: pd.DataFrame) -> pd.DataFrame:
    labels = normalize_plate_map(plate_map)
    merged = tidy.merge(labels, on="well", how="left")
    for column in PLATE_MAP_COLUMNS:
        if column != "well" and column in merged.columns:
            merged[column] = merged[column].fillna("")
    return merged


def qc_plate_map(labeled: pd.DataFrame, settings: dict[str, Any] | None = None) -> list[str]:
    settings = settings or {}
    warnings = []
    well_labels = labeled[["well", "condition"]].drop_duplicates()
    unlabeled = well_labels[well_labels["condition"].astype(str).str.strip() == ""]
    if not unlabeled.empty:
        warnings.append(f"{len(unlabeled)} detected wells have no assigned condition.")
    if settings.get("blank_subtraction", {}).get("enabled"):
        if not (labeled.get("role", "").astype(str).str.lower() == "blank").any():
            warnings.append("Blank subtraction is enabled but no blank wells are assigned.")
    if settings.get("control_normalization", {}).get("enabled"):
        roles = labeled.get("role", "").astype(str).str.lower()
        if not roles.isin(["vehicle", "control"]).any():
            warnings.append("Control normalization is enabled but no vehicle/control wells are assigned.")
    return warnings


def validate_analysis_settings(plate_map: pd.DataFrame, settings: dict[str, Any] | None = None) -> list[str]:
    """Return blocking setup errors before running the analysis pipeline."""
    settings = settings or {}
    labels = normalize_plate_map(plate_map)
    roles = labels["role"].astype(str).str.strip().str.lower()
    conditions = labels["condition"].astype(str).str.strip()
    errors = []

    if settings.get("blank_subtraction", {}).get("enabled") and not (roles == "blank").any():
        errors.append("Blank subtraction is enabled, but no wells are marked as blank.")
    if settings.get("control_normalization", {}).get("enabled") and not roles.isin(["vehicle", "control"]).any():
        errors.append("Vehicle/control normalization is enabled, but no wells are marked as vehicle or control.")
    if not conditions.astype(bool).any():
        errors.append("No well conditions are assigned. Label at least one detected well before analyzing.")
    return errors
