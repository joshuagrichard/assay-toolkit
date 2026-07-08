from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

ROWS = "ABCDEFGH"
COLUMNS = range(1, 13)
WELLS_96 = [f"{row}{col}" for row in ROWS for col in COLUMNS]
WELL_RE = re.compile(r"^([A-H])0?([1-9]|1[0-2])$", re.IGNORECASE)
TIME_RE = re.compile(r"^([A-H])0?([1-9]|1[0-2])T$", re.IGNORECASE)


@dataclass
class ParsedPlateReaderFile:
    tidy: pd.DataFrame
    metadata: dict[str, Any]
    detected_wells: list[str]
    warnings: list[str]


def canonical_well(value: str) -> str | None:
    match = WELL_RE.match(str(value).strip())
    if not match:
        return None
    return f"{match.group(1).upper()}{int(match.group(2))}"


def canonical_time_col(value: str) -> str | None:
    match = TIME_RE.match(str(value).strip())
    if not match:
        return None
    return f"{match.group(1).upper()}{int(match.group(2))}T"


def _read_text(path: Path) -> list[str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding).splitlines()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").splitlines()


def _split_line(line: str) -> list[str]:
    if "\t" in line:
        return [cell.strip() for cell in line.split("\t")]
    try:
        return [cell.strip() for cell in next(csv.reader([line]))]
    except Exception:
        return [cell.strip() for cell in re.split(r"\s+", line.strip())]


def _looks_like_header(cells: list[str]) -> bool:
    well_count = sum(1 for cell in cells if canonical_well(cell))
    time_count = sum(1 for cell in cells if canonical_time_col(cell))
    return well_count >= 1 and time_count >= 1


def _metadata_from_lines(lines: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {"raw_metadata_lines": lines[:50]}
    for line in lines:
        if line.startswith("##") and "=" in line:
            key, value = line[2:].split("=", 1)
            metadata[key.strip()] = value.strip()
        plate_match = re.search(r"\bPlate:\s*([^\t, ]+)", line, flags=re.IGNORECASE)
        if plate_match:
            metadata["plate_id"] = plate_match.group(1)
    metadata.setdefault("plate_id", "Plate1")
    return metadata


def _load_text_table(path: Path) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    lines = _read_text(path)
    header_index = None
    for idx, line in enumerate(lines):
        if _looks_like_header(_split_line(line)):
            header_index = idx
            break
    if header_index is None:
        raise ValueError("Could not find a plate reader data header with paired well/time columns like A1T and A1.")

    header = _split_line(lines[header_index])
    delimiter = "\t" if "\t" in lines[header_index] else None
    table_text = "\n".join(lines[header_index + 1 :])
    if delimiter == "\t":
        df = pd.read_csv(StringIO(table_text), sep="\t", names=header)
    else:
        df = pd.read_csv(StringIO(table_text), sep=None, engine="python", names=header)
    return df, _metadata_from_lines(lines[:header_index]), lines[:header_index]


def _load_excel_table(path: Path) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    raw = pd.read_excel(path, header=None, dtype=object)
    header_index = None
    for idx, row in raw.iterrows():
        cells = ["" if pd.isna(cell) else str(cell).strip() for cell in row.tolist()]
        if _looks_like_header(cells):
            header_index = idx
            break
    if header_index is None:
        raise ValueError("Could not find a plate reader data header in the Excel file.")
    header = ["" if pd.isna(cell) else str(cell).strip() for cell in raw.iloc[header_index].tolist()]
    df = raw.iloc[header_index + 1 :].copy()
    df.columns = header
    df = df.dropna(how="all")
    metadata_lines = [" ".join(str(x) for x in raw.iloc[i].dropna().tolist()) for i in range(header_index)]
    return df, _metadata_from_lines(metadata_lines), metadata_lines


def parse_plate_reader_file(path: Path) -> ParsedPlateReaderFile:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        raw_df, metadata, _ = _load_excel_table(path)
    elif suffix in {".txt", ".csv", ".tsv"}:
        raw_df, metadata, _ = _load_text_table(path)
    else:
        raise ValueError(f"Unsupported plate reader file type: {suffix}")

    metadata["source_file"] = path.name
    temperature_col = next((col for col in raw_df.columns if "temperature" in str(col).lower()), None)
    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    detected_wells: list[str] = []

    column_lookup = {str(col).strip(): col for col in raw_df.columns}
    for well in WELLS_96:
        value_col = column_lookup.get(well)
        time_col = column_lookup.get(f"{well}T")
        if value_col is None:
            continue
        detected_wells.append(well)
        if time_col is None:
            warnings.append(f"Missing paired time column for {well}; row index used as time.")

        for idx, row in raw_df.iterrows():
            raw_value = pd.to_numeric(row.get(value_col), errors="coerce")
            if pd.isna(raw_value):
                continue
            time_value = pd.to_numeric(row.get(time_col), errors="coerce") if time_col is not None else idx
            temperature = pd.to_numeric(row.get(temperature_col), errors="coerce") if temperature_col else pd.NA
            records.append(
                {
                    "plate_id": metadata.get("plate_id", "Plate1"),
                    "well": well,
                    "row": well[0],
                    "column": int(well[1:]),
                    "time": time_value,
                    "temperature": temperature,
                    "raw_value": raw_value,
                    "source_file": path.name,
                }
            )

    if not records:
        raise ValueError("No numeric well readings were detected in the uploaded file.")

    tidy = pd.DataFrame(records)
    missing = sorted(set(WELLS_96) - set(detected_wells))
    if missing:
        warnings.append(f"{len(missing)} wells had no detected signal column.")
    if tidy["time"].isna().any():
        warnings.append("Some readings have missing time values.")
    return ParsedPlateReaderFile(tidy=tidy, metadata=metadata, detected_wells=detected_wells, warnings=warnings)

