#!/usr/bin/env bash
set -euo pipefail

PORTS=(8000 8001 8002 8003)
PIDS=()

for port in "${PORTS[@]}"; do
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] && PIDS+=("${pid}")
  done < <(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)
done

if [[ "${#PIDS[@]}" -eq 0 ]]; then
  echo "No dev servers found on ports ${PORTS[*]}."
  exit 0
fi

UNIQUE_PIDS=($(printf "%s\n" "${PIDS[@]}" | sort -u))
echo "Stopping dev server process(es): ${UNIQUE_PIDS[*]}"
kill "${UNIQUE_PIDS[@]}" 2>/dev/null || true
sleep 1

STILL_RUNNING=()
for pid in "${UNIQUE_PIDS[@]}"; do
  if kill -0 "${pid}" 2>/dev/null; then
    STILL_RUNNING+=("${pid}")
  fi
done

if [[ "${#STILL_RUNNING[@]}" -gt 0 ]]; then
  echo "Force stopping unresponsive process(es): ${STILL_RUNNING[*]}"
  kill -9 "${STILL_RUNNING[@]}" 2>/dev/null || true
fi

echo "Dev server ports are clear."
