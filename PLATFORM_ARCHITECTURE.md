# Translational Assay Toolkit Architecture

This repository now has a small platform boundary around the scratch assay proof of concept.

## Layers

- `assay_platform/core.py`: shared contracts for all tools. Each tool has a manifest, accepted file extensions, editable parameters, and a `run(input_dir, output_dir, params)` function.
- `assay_platform/tools/`: assay-specific adapters. `scratch_wound.py` wraps the current scratch assay code without forcing the website to know its implementation details.
- `assay_platform/registry.py`: central registry used by the web app to list and run available tools.
- `assay_platform/web_app.py`: FastAPI app with endpoints for tool discovery, upload, execution, and result downloads.
- `web/static/`: initial browser UI for choosing a tool, uploading files, setting parameters, running analysis, and downloading CSV/artifacts.

## Adding The Next Assay Tool

1. Create a module under `assay_platform/tools/`, for example `flexstation_calcium.py`.
2. Implement a `run_<tool>(input_dir, output_dir, params)` function that returns `AnalysisJobResult`.
3. Define an `AssayTool` with metadata, accepted extensions, and `ToolParameter` entries.
4. Register it in `assay_platform/registry.py`.

This keeps FlexStation calcium, confocal calcium, and scratch/wound analysis independent while giving the website one consistent interface.

## Running The Web App

Install the web-only dependencies:

```bash
python -m pip install -r requirements-web.txt
```

Then run:

```bash
python -m uvicorn assay_platform.web_app:app --reload
```

Open `http://127.0.0.1:8000`.
