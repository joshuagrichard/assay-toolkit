import zipfile
from pathlib import Path

import pandas as pd
from assay_platform.tools.plate_reader.exports import prism_wide, write_exports
from assay_platform.tools.plate_reader.metrics import auc_for_trace
from assay_platform.tools.plate_reader.normalization import (
    apply_baseline_normalization,
    apply_blank_subtraction,
    apply_control_normalization,
)
from assay_platform.tools.plate_reader.parser import parse_plate_reader_file
from assay_platform.tools.plate_reader.plate_map import merge_plate_map, normalize_plate_map, validate_analysis_settings

SAMPLE = Path("samples/plate_reader/flex_like_sample.txt")


def test_parser_detects_well_time_columns_and_long_format():
    parsed = parse_plate_reader_file(SAMPLE)
    assert {"A1", "A2", "A3", "B1", "B2", "B3"}.issubset(set(parsed.detected_wells))
    assert {"plate_id", "well", "time", "temperature", "raw_value", "source_file"}.issubset(parsed.tidy.columns)
    assert len(parsed.tidy[parsed.tidy["well"] == "B1"]) == 4


def test_blank_subtraction_timepoint():
    parsed = parse_plate_reader_file(SAMPLE)
    plate_map = normalize_plate_map([
        {"well": "A1", "condition": "blank", "role": "blank"},
        {"well": "A2", "condition": "blank", "role": "blank"},
        {"well": "B1", "condition": "pdgf", "role": "treated"},
    ])
    labeled = merge_plate_map(parsed.tidy, plate_map)
    out = apply_blank_subtraction(labeled, mode="timepoint")
    b1_t0 = out[(out["well"] == "B1") & (out["time"] == 0)]["blank_subtracted"].iloc[0]
    assert b1_t0 == 104


def test_baseline_normalization_delta():
    df = pd.DataFrame({"well": ["A1", "A1"], "time": [0, 1], "value": [10.0, 15.0]})
    out = apply_baseline_normalization(df, "value", "delta")
    assert out["baseline_normalized"].tolist() == [0.0, 5.0]


def test_control_normalization_timepoint():
    df = pd.DataFrame(
        {
            "well": ["A1", "B1"],
            "time": [0, 0],
            "role": ["vehicle", "treated"],
            "value": [10.0, 20.0],
        }
    )
    out = apply_control_normalization(df, "value", "timepoint")
    assert out[out["well"] == "B1"]["control_normalized"].iloc[0] == 2.0


def test_auc_calculation():
    trace = pd.DataFrame({"time": [0, 1, 2], "analysis_value": [0.0, 1.0, 2.0]})
    assert auc_for_trace(trace, "analysis_value") == 2.0


def test_prism_export_formatting():
    metrics = pd.DataFrame(
        {
            "well": ["B1", "B2"],
            "condition": ["pdgf", "pdgf"],
            "replicate": [1, 2],
            "endpoint": [3.0, 4.0],
        }
    )
    wide = prism_wide(metrics, "endpoint", "condition")
    assert wide["pdgf"].tolist() == [3.0, 4.0]


def test_validate_analysis_settings_requires_blank_role_when_enabled():
    plate_map = normalize_plate_map([{"well": "A1", "condition": "dmso", "role": "vehicle"}])
    errors = validate_analysis_settings(plate_map, {"blank_subtraction": {"enabled": True}})
    assert any("no wells are marked as blank" in error for error in errors)


def test_validate_analysis_settings_requires_control_role_when_enabled():
    plate_map = normalize_plate_map([{"well": "A1", "condition": "pdgf", "role": "treated"}])
    errors = validate_analysis_settings(plate_map, {"control_normalization": {"enabled": True}})
    assert any("no wells are marked as vehicle or control" in error for error in errors)


def test_export_zip_does_not_include_itself(tmp_path):
    df = pd.DataFrame({"well": ["A1"], "time": [0], "raw_value": [1.0], "analysis_value": [1.0]})
    plate_map = normalize_plate_map([{"well": "A1", "condition": "dmso"}])
    paths = write_exports(
        tmp_path,
        raw_tidy=df,
        labeled=df,
        processed=df,
        summary=pd.DataFrame({"time": [0], "mean": [1.0], "std": [0.0], "n": [1], "sem": [0.0]}),
        metrics=pd.DataFrame({"well": ["A1"], "condition": ["dmso"], "endpoint": [1.0]}),
        stats_table=pd.DataFrame(),
        plate_map=plate_map,
        settings={},
    )
    with zipfile.ZipFile(paths["zip"]) as zip_file:
        names = zip_file.namelist()
    assert "plate_reader_exports.zip" not in names
    assert "processed_tidy.csv" in names
