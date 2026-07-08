from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from assay_platform.core import AnalysisJobResult, AssayTool, ToolParameter

DEFAULTS: dict[str, Any] = {
    "wound_geometry_mode": "auto",
    "blur_kernel": 5,
    "background_kernel": 101,
    "std_window": 21,
    "residual_window": 9,
    "corridor_smooth_window": 31,
    "min_corridor_width": 20,
    "threshold_mode": "hybrid",
    "percentile_value": 60.0,
    "min_open_object_size": 100,
    "morph_close": 5,
    "morph_open": 3,
    "leading_edge_search_radius": 120,
    "edge_smooth_window": 21,
    "min_cell_run_width": 12,
}


def _parameters() -> tuple[ToolParameter, ...]:
    return (
        ToolParameter(
            "wound_geometry_mode",
            "Wound geometry",
            "choice",
            "auto",
            description="Use insert for uniform barrier wounds, freehand for pipette-tip scratches, or auto to classify from time-0 images.",
            choices=("auto", "insert", "freehand"),
        ),
        ToolParameter("blur_kernel", "Blur kernel", "int", 5, minimum=1, maximum=999),
        ToolParameter("background_kernel", "Background kernel", "int", 101, minimum=1, maximum=9999),
        ToolParameter("std_window", "Local STD window", "int", 21, minimum=1, maximum=999),
        ToolParameter("residual_window", "Residual window", "int", 9, minimum=1, maximum=999),
        ToolParameter("corridor_smooth_window", "Time-0 smoothing", "int", 31, minimum=1, maximum=999),
        ToolParameter("min_corridor_width", "Minimum wound width", "int", 20, minimum=1, maximum=5000),
        ToolParameter(
            "threshold_mode",
            "Threshold mode",
            "choice",
            "hybrid",
            choices=("percentile", "otsu", "hybrid"),
        ),
        ToolParameter("percentile_value", "Percentile", "float", 60.0, minimum=0, maximum=100),
        ToolParameter("min_open_object_size", "Minimum open object size", "int", 100, minimum=1),
        ToolParameter("morph_close", "Morph close", "int", 5, minimum=1, maximum=999),
        ToolParameter("morph_open", "Morph open", "int", 3, minimum=1, maximum=999),
        ToolParameter("leading_edge_search_radius", "Edge search radius", "int", 120, minimum=1, maximum=5000),
        ToolParameter("edge_smooth_window", "Edge smoothing", "int", 21, minimum=1, maximum=999),
        ToolParameter("min_cell_run_width", "Minimum cell run width", "int", 12, minimum=1, maximum=5000),
    )


def _coerce_params(params: dict[str, Any]) -> dict[str, Any]:
    merged = {**DEFAULTS, **(params or {})}
    allowed_geometry_modes = {"auto", "insert", "freehand"}
    if merged["wound_geometry_mode"] not in allowed_geometry_modes:
        raise ValueError(f"wound_geometry_mode must be one of {sorted(allowed_geometry_modes)}")
    allowed_modes = {"percentile", "otsu", "hybrid"}
    if merged["threshold_mode"] not in allowed_modes:
        raise ValueError(f"threshold_mode must be one of {sorted(allowed_modes)}")
    return merged


def run_scratch_wound(input_dir: Path, output_dir: Path, params: dict[str, Any]) -> AnalysisJobResult:
    import pandas as pd
    from scratch_assay_analysis import analyze_folder

    output_dir.mkdir(parents=True, exist_ok=True)
    cfg = _coerce_params(params)

    df = analyze_folder(
        input_dir=Path(input_dir),
        output_dir=Path(output_dir),
        **cfg,
    )

    csv_path = output_dir / "scratch_results.csv"
    zip_path = shutil.make_archive(str(output_dir / "artifacts"), "zip", output_dir)

    summary = {
        "images_analyzed": int(len(df)),
        "successful_images": int(df["error"].isna().sum()) if "error" in df.columns else int(len(df)),
        "failed_images": int(df["error"].notna().sum()) if "error" in df.columns else 0,
    }
    if "percent_closure" in df.columns:
        closure = pd.to_numeric(df["percent_closure"], errors="coerce").dropna()
        if not closure.empty:
            summary["median_percent_closure"] = float(closure.median())

    return AnalysisJobResult(
        tool_id="scratch_wound",
        output_dir=output_dir,
        results_table=csv_path if csv_path.exists() else None,
        artifacts={"zip": Path(zip_path)},
        summary=summary,
    )


scratch_wound_tool = AssayTool(
    id="scratch_wound",
    name="Scratch Assay Analyzer",
    category="Image analysis",
    description="Detects the time-0 wound corridor, anchors follow-up ROIs, segments residual open area, and reports closure metrics.",
    accepted_extensions=(".tif", ".tiff", ".png", ".jpg", ".jpeg"),
    parameters=_parameters(),
    run=run_scratch_wound,
)
