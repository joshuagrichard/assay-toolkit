from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from assay_platform.tools.plate_reader.exports import write_exports
from assay_platform.tools.plate_reader.metrics import calculate_well_metrics, summarize_replicates
from assay_platform.tools.plate_reader.normalization import process_measurements
from assay_platform.tools.plate_reader.parser import parse_plate_reader_file
from assay_platform.tools.plate_reader.plate_map import (
    merge_plate_map,
    normalize_plate_map,
    qc_plate_map,
    validate_analysis_settings,
)
from assay_platform.tools.plate_reader.stats import basic_stats


def analyze_plate_reader_file(input_path: Path,
                              output_dir: Path,
                              plate_map_records: list[dict[str, Any]],
                              settings: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_plate_reader_file(input_path)
    plate_map = normalize_plate_map(plate_map_records)
    setup_errors = validate_analysis_settings(plate_map, settings)
    if setup_errors:
        raise ValueError(" ".join(setup_errors))
    labeled = merge_plate_map(parsed.tidy, plate_map)
    processed = process_measurements(labeled, settings)
    metrics = calculate_well_metrics(processed, settings)
    summary = summarize_replicates(processed)
    stats_table = basic_stats(metrics, settings.get("statistics", {}))
    warnings = parsed.warnings + qc_plate_map(labeled, settings)
    paths = write_exports(output_dir, parsed.tidy, labeled, processed, summary, metrics, stats_table, plate_map, settings)
    return {
        "parsed": parsed,
        "plate_map": plate_map,
        "labeled": labeled,
        "processed": processed,
        "metrics": metrics,
        "summary": summary,
        "stats": stats_table,
        "warnings": warnings,
        "paths": paths,
    }
