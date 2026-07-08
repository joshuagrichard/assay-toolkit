#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-8000}"

"${ROOT_DIR}/scripts/stop_dev_server.sh" >/dev/null 2>&1 || true

cd "${ROOT_DIR}"
echo "Starting Translational Assay Toolkit on http://127.0.0.1:${PORT}"
exec python3 -m uvicorn assay_platform.web_app:app --host 127.0.0.1 --port "${PORT}"
