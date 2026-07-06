import json
import shutil
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from uuid import uuid4

from assay_platform.registry import registry

BASE_DIR = Path(__file__).resolve().parents[1]
JOB_ROOT = BASE_DIR / "web_jobs"
STATIC_DIR = BASE_DIR / "web" / "static"
PLATE_READER_STATIC_DIR = BASE_DIR / "web" / "plate_reader"


def _safe_upload_path(filename: str) -> Path | None:
    raw = (filename or "").replace("\\", "/")
    pure = PurePosixPath(raw)
    if pure.is_absolute():
        return None
    parts = [part for part in pure.parts if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        return None
    return Path(*parts)


def _job_file_url(job_id: str, area: str, relative_path: Path) -> str:
    parts = [area, *relative_path.parts]
    return f"/api/jobs/{job_id}/files/" + "/".join(quote(part) for part in parts)


def _review_items(job_id: str, input_dir: Path, output_dir: Path, results_table: Path | None) -> list[dict]:
    if results_table is None or not results_table.exists():
        return []

    import pandas as pd
    from scratch_assay_analysis import artifact_stem

    df = pd.read_csv(results_table)
    items = []
    for _, row in df.iterrows():
        filename = str(row.get("filename", ""))
        if not filename:
            continue
        stem = artifact_stem(Path(filename))
        item = {
            "filename": filename,
            "time_value": None if pd.isna(row.get("time_value")) else row.get("time_value"),
            "condition_id": None if pd.isna(row.get("condition_id")) else row.get("condition_id"),
            "well_id": None if pd.isna(row.get("well_id")) else row.get("well_id"),
            "field_id": None if pd.isna(row.get("field_id")) else row.get("field_id"),
            "group_id": None if pd.isna(row.get("group_id")) else row.get("group_id"),
            "percent_closure": None if pd.isna(row.get("percent_closure")) else row.get("percent_closure"),
            "open_area_px": None if pd.isna(row.get("residual_open_area_px")) else row.get("residual_open_area_px"),
            "selected_wound_geometry": None if pd.isna(row.get("selected_wound_geometry")) else row.get("selected_wound_geometry"),
            "t0_geometry_score": None if pd.isna(row.get("t0_geometry_score")) else row.get("t0_geometry_score"),
            "error": None if pd.isna(row.get("error")) else row.get("error"),
            "images": {},
        }

        source_rel_path = Path(filename)
        source_path = input_dir / source_rel_path
        overlay_path = output_dir / "overlays" / f"{stem}_overlay.png"
        mask_path = output_dir / "masks" / f"{stem}_open_mask.png"
        debug_path = output_dir / "debug" / f"{stem}_debug.png"

        if source_path.exists():
            item["images"]["source"] = _job_file_url(job_id, "input", source_rel_path)
        if overlay_path.exists():
            item["images"]["overlay"] = _job_file_url(job_id, "output", Path("overlays") / overlay_path.name)
        if mask_path.exists():
            item["images"]["mask"] = _job_file_url(job_id, "output", Path("masks") / mask_path.name)
        if debug_path.exists():
            item["images"]["debug"] = _job_file_url(job_id, "output", Path("debug") / debug_path.name)

        items.append(item)
    return items


def _resolve_job_file(job_id: str, relative_path: str) -> Path | None:
    parts = Path(relative_path)
    if parts.is_absolute() or ".." in parts.parts or len(parts.parts) < 2:
        return None
    area = parts.parts[0]
    if area not in {"input", "output"}:
        return None
    path = JOB_ROOT / job_id / parts
    try:
        path.resolve().relative_to((JOB_ROOT / job_id).resolve())
    except ValueError:
        return None
    return path


def _json_records(df, limit: int = 250) -> list[dict]:
    import numpy as np
    import pandas as pd

    if df is None or df.empty:
        return []
    clean = df.head(limit).replace([np.inf, -np.inf], np.nan)
    clean = clean.astype(object).where(pd.notna(clean), None)
    return clean.to_dict(orient="records")


def create_app():
    try:
        from fastapi import FastAPI, File, Form, HTTPException, UploadFile
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
        from starlette.concurrency import run_in_threadpool
    except ImportError as exc:
        raise RuntimeError(
            "The web app requires FastAPI and Uvicorn. Install them with: "
            "python -m pip install fastapi uvicorn python-multipart"
        ) from exc

    app = FastAPI(title="Translational Assay Toolkit")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/plate-reader")
    def plate_reader_page():
        return FileResponse(PLATE_READER_STATIC_DIR / "index.html")

    app.mount("/plate-reader-static", StaticFiles(directory=PLATE_READER_STATIC_DIR), name="plate_reader_static")

    @app.get("/api/tools")
    def list_tools():
        return registry.manifest()

    @app.post("/api/tools/{tool_id}/jobs")
    async def run_tool(
        tool_id: str,
        params_json: str = Form("{}"),
        files: list[UploadFile] = File(...),
    ):
        try:
            tool = registry.get(tool_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            params = json.loads(params_json or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="params_json must be valid JSON") from exc

        job_id = uuid4().hex
        job_dir = JOB_ROOT / job_id
        input_dir = job_dir / "input"
        output_dir = job_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        allowed = {ext.lower() for ext in tool.accepted_extensions}
        for upload in files:
            rel_path = _safe_upload_path(upload.filename or "")
            if rel_path is None:
                continue
            if rel_path.suffix.lower() not in allowed:
                raise HTTPException(status_code=400, detail=f"Unsupported file type: {rel_path}")
            destination = input_dir / rel_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as out:
                shutil.copyfileobj(upload.file, out)

        try:
            result = tool.run(input_dir, output_dir, params)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        payload = result.to_dict()
        payload["job_id"] = job_id
        if result.results_table:
            payload["results_csv_url"] = _job_file_url(job_id, "output", Path("scratch_results.csv"))
        if "zip" in result.artifacts:
            payload["artifacts_zip_url"] = _job_file_url(job_id, "output", Path("artifacts.zip"))
        payload["review_items"] = _review_items(job_id, input_dir, output_dir, result.results_table)
        return payload

    @app.post("/api/plate-reader/parse")
    async def plate_reader_parse(file: UploadFile = File(...)):
        from assay_platform.tools.plate_reader.parser import parse_plate_reader_file
        from assay_platform.tools.plate_reader.plate_map import empty_plate_map

        rel_path = _safe_upload_path(file.filename or "")
        if rel_path is None:
            raise HTTPException(status_code=400, detail="Invalid upload path")
        if rel_path.suffix.lower() not in {".txt", ".csv", ".tsv", ".xls", ".xlsx"}:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {rel_path.suffix}")

        job_id = uuid4().hex
        job_dir = JOB_ROOT / job_id
        input_dir = job_dir / "input"
        output_dir = job_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        raw_path = input_dir / rel_path.name
        with raw_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)

        try:
            parsed = parse_plate_reader_file(raw_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        parsed.tidy.to_csv(output_dir / "raw_tidy.csv", index=False)
        metadata_path = output_dir / "parse_metadata.json"
        metadata_path.write_text(json.dumps(parsed.metadata, indent=2), encoding="utf-8")
        return {
            "job_id": job_id,
            "metadata": parsed.metadata,
            "detected_wells": parsed.detected_wells,
            "warnings": parsed.warnings,
            "preview": _json_records(parsed.tidy),
            "plate_map_template": _json_records(empty_plate_map(), limit=96),
            "raw_tidy_url": _job_file_url(job_id, "output", Path("raw_tidy.csv")),
        }

    @app.post("/api/plate-reader/{job_id}/analyze")
    async def plate_reader_analyze(job_id: str, payload: dict):
        from assay_platform.tools.plate_reader.pipeline import analyze_plate_reader_file
        from assay_platform.tools.plate_reader.plate_map import normalize_plate_map, validate_analysis_settings

        input_dir = JOB_ROOT / job_id / "input"
        output_dir = JOB_ROOT / job_id / "output"
        if not input_dir.exists():
            raise HTTPException(status_code=404, detail="Plate reader job not found")
        input_files = [p for p in input_dir.iterdir() if p.is_file()]
        if not input_files:
            raise HTTPException(status_code=404, detail="No uploaded plate reader file found")
        plate_map = normalize_plate_map(payload.get("plate_map", []))
        settings = payload.get("settings", {})
        setup_errors = validate_analysis_settings(plate_map, settings)
        if setup_errors:
            raise HTTPException(status_code=400, detail={"message": "Analysis setup needs attention.", "errors": setup_errors})
        try:
            result = await run_in_threadpool(
                analyze_plate_reader_file,
                input_files[0],
                output_dir,
                plate_map.to_dict(orient="records"),
                settings,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        paths = result["paths"]
        return {
            "job_id": job_id,
            "warnings": result["warnings"],
            "summary_preview": _json_records(result["summary"]),
            "metrics_preview": _json_records(result["metrics"]),
            "stats_preview": _json_records(result["stats"]),
            "processed_preview": _json_records(result["processed"]),
            "downloads": {key: _job_file_url(job_id, "output", Path(path.name)) for key, path in paths.items() if path.exists() and path.parent == output_dir},
        }

    @app.get("/api/jobs/{job_id}/files/{relative_path:path}")
    def job_file(job_id: str, relative_path: str):
        path = _resolve_job_file(job_id, relative_path)
        if path is None:
            raise HTTPException(status_code=400, detail="Invalid file path")
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(path, filename=path.name)

    return app


app = create_app()
